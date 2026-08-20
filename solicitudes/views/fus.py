import os
import re

from django.conf import settings
from django.db import connection
from django.db.models import Count, Q, FloatField
from django.db.models.expressions import RawSQL
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from autenticacion.models import CorreoAutorizado
from catalogos.models import MedioRecepcion, Estatus
from ..models import FUS, Evidencia, Turnado, Actividad, SeguimientoRespuesta
from ..serializers import FUSSerializer
from ..services import generar_folio, guardar_evidencias, eliminar_evidencias
from ..utils import resolver_nombre
from ..helpers import _resolver_unidad_administrativa, emails_de_fus, mapa_correos_autorizados
from .helpers import _rol, _log, ROLES_PARTICULAR, _propietario_fus, _puede_ver_fus


# ── FUS ─────────────────────────────────────────────────────────────────────

# Caracteres con significado especial en MATCH()...AGAINST(... IN BOOLEAN
# MODE) (+ - > < ( ) ~ * " @) — se quitan de cada palabra para que el texto
# de búsqueda del usuario nunca se interprete como operador de búsqueda.
_FULLTEXT_OPERADORES = re.compile(r'[+\-><()~*"@]')
# innodb_ft_min_token_size por defecto en MySQL/InnoDB — palabras más cortas
# no están en el índice FULLTEXT y MATCH() nunca las encuentra.
_FULLTEXT_MIN_TOKEN = 3


def _q_estatus_particular_fus(clave):
    """Arma el Q() de un solo estatus/temporalidad para FUS.estatusParticular
    — factorizado de FUSListCreateView.get para reusarlo tal cual al filtrar
    (varios claves con OR) y al calcular los conteos por chip (uno a la vez,
    sobre el queryset sin el propio filtro de estatus/prioridad aplicado)."""
    if clave == 'Vencido':
        # Indicador de temporalidad, no de estatus: por fechaLimite, sin
        # importar en qué estatus del trámite esté el FUS — salvo Concluido,
        # ya cerrado, donde la temporalidad deja de aplicar (mismo criterio
        # que FUSSerializer.get_estadoTemporalidad).
        return Q(fechaLimite__lt=timezone.now()) & ~Q(estatusParticular_id='Concluido')
    if clave == 'PorVencer':
        from datetime import timedelta
        ahora = timezone.now()
        return Q(
            fechaLimite__gte=ahora, fechaLimite__lte=ahora + timedelta(hours=24),
        ) & ~Q(estatusParticular_id='Concluido')
    if clave == 'Pendiente_validacion':
        # Con un solo Titular turnado (sin comisionar), marcar "Atendido"
        # deja fus.estatusParticular en 'Atendido' — el que de verdad pasa a
        # 'Pendiente_validacion' es ese turnado (MarcarTurnadoAtendidoView,
        # turnado.py), porque con varias personas "Atendido" no implica que
        # todas ya estén listas. La tarjeta ya refleja esto mostrando el
        # estatus del turnado cuando es el único activo
        # (FUSSerializer.get_estatusVisual) — este filtro necesita el mismo
        # criterio, o "Por validar" nunca encuentra esos FUS aunque la
        # tarjeta sí diga "Por validar".
        fus_un_turnado = (
            Turnado.objects.filter(activo=1)
            .values('idFus_id').annotate(n=Count('id')).filter(n=1)
            .values('idFus_id')
        )
        fus_un_turnado_pendiente = Turnado.objects.filter(
            activo=1, estatusTitular_id='Pendiente_validacion',
            idFus_id__in=fus_un_turnado,
        ).values('idFus_id')
        return Q(estatusParticular_id='Pendiente_validacion') | Q(pk__in=fus_un_turnado_pendiente)
    return Q(estatusParticular_id=clave)


def _termino_fulltext_booleano(search):
    """Arma el término para MATCH()...AGAINST(... IN BOOLEAN MODE) a partir
    de texto libre: separa por palabras, limpia operadores de modo booleano
    y agrega '*' a cada palabra para aproximar el "contiene" de icontains.
    Devuelve None si ninguna palabra alcanza innodb_ft_min_token_size — en
    ese caso el llamador debe seguir usando icontains para esas columnas,
    porque el índice no las cubre y MATCH() no encontraría nada."""
    palabras = []
    for palabra in search.split():
        limpia = _FULLTEXT_OPERADORES.sub('', palabra)
        if len(limpia) >= _FULLTEXT_MIN_TOKEN:
            palabras.append(f'{limpia}*')
    return ' '.join(palabras) if palabras else None


class FUSListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        rol = _rol(request.user)
        if rol not in ROLES_PARTICULAR:
            return Response({'detail': 'No autorizado.'}, status=403)

        qs = FUS.objects.filter(activo=1).select_related(
            'idSolicitanteInterno', 'idMedioRecepcion', 'idComisionado'
        ).prefetch_related('evidencias', 'turnados__idDestinatario')

        if rol == 'EQUIPO_PARTICULAR':
            propietario = _propietario_fus(request.user)
            qs = qs.filter(idSolicitanteInterno=propietario) if propietario else qs.none()

        estatus_raw = request.query_params.get('estatusParticular')
        prioridad   = request.query_params.get('prioridad')
        search      = request.query_params.get('search')
        folio       = request.query_params.get('folio')
        if folio:
            # Consulta puntual desde dashboard, notificaciones o bitácora
            # (mismo criterio que MisTurnadosView.get). Se filtra antes de
            # paginar para que el FUS se encuentre aunque no esté entre los
            # más recientes de la bandeja.
            qs = qs.filter(folio=folio)
        if search:
            emails_nombre = list(CorreoAutorizado.objects.filter(nombre__icontains=search).values_list('email', flat=True))
            # Columnas sin índice FULLTEXT (campos cortos/estructurados,
            # donde lo que se busca es una subcadena: parte de un teléfono,
            # un dominio de correo) — siguen con icontains, sin cambios.
            condiciones = (
                Q(folio__icontains=search) |
                Q(medioEspecificacion__icontains=search) |
                Q(criterios__icontains=search) |
                Q(nombreExterno__icontains=search) |
                Q(telefonoExterno__icontains=search) |
                Q(correoExterno__icontains=search) |
                Q(idMedioRecepcion__nombreMedio__icontains=search) |
                Q(idSolicitanteInterno__email__icontains=search) |
                Q(idSolicitanteInterno__email__in=emails_nombre) |
                Q(turnados__idMedio__nombreMedio__icontains=search) |
                Q(turnados__idRemitente__email__icontains=search) |
                Q(turnados__idRemitente__email__in=emails_nombre) |
                Q(turnados__idDestinatario__email__icontains=search) |
                Q(turnados__idDestinatario__email__in=emails_nombre) |
                Q(turnados__seguimientos__descripcionActividad__icontains=search) |
                Q(turnados__seguimientos__accionTexto__icontains=search)
            )
            # MATCH()...AGAINST() es sintaxis de MySQL — en otros motores
            # (Postgres/Neon en Render) el índice FULLTEXT ni existe (ver
            # migración 0033), así que ahí siempre se cae al respaldo con
            # icontains de abajo en vez de emitir una consulta inválida.
            termino_fulltext = _termino_fulltext_booleano(search) if connection.vendor == 'mysql' else None
            if termino_fulltext:
                # Migración 0033: usa los índices FULLTEXT de
                # descripcion/contexto, evidencias y turnados en vez del
                # escaneo multi-tabla con icontains. Cada MATCH() corre
                # sobre su propia tabla base (sin depender del alias que
                # arme el ORM para los JOIN de evidencias__/turnados__) y
                # se pliega de vuelta a IDs de FUS.
                ids_por_fus = FUS.objects.annotate(
                    _rel=RawSQL(
                        'MATCH(descripcion, contexto) AGAINST (%s IN BOOLEAN MODE)',
                        [termino_fulltext], output_field=FloatField(),
                    )
                ).filter(_rel__gt=0).values('pk')
                ids_por_evidencia = Evidencia.objects.annotate(
                    _rel=RawSQL(
                        'MATCH(nombre_archivo, comentarios) AGAINST (%s IN BOOLEAN MODE)',
                        [termino_fulltext], output_field=FloatField(),
                    )
                ).filter(_rel__gt=0).values('idFus')
                ids_por_turnado = Turnado.objects.annotate(
                    _rel=RawSQL(
                        'MATCH(solicitud_texto) AGAINST (%s IN BOOLEAN MODE)',
                        [termino_fulltext], output_field=FloatField(),
                    )
                ).filter(_rel__gt=0).values('idFus')
                condiciones |= (
                    Q(pk__in=ids_por_fus) |
                    Q(pk__in=ids_por_evidencia) |
                    Q(pk__in=ids_por_turnado)
                )
            else:
                # Término demasiado corto para el índice FULLTEXT
                # (innodb_ft_min_token_size) — respaldo con icontains para
                # no perder resultados que sí encontraba antes.
                condiciones |= (
                    Q(descripcion__icontains=search) |
                    Q(contexto__icontains=search) |
                    Q(evidencias__nombreArchivo__icontains=search) |
                    Q(evidencias__comentarios__icontains=search) |
                    Q(turnados__solicitudTexto__icontains=search)
                )
            qs = qs.filter(condiciones).distinct()

        # Snapshot previo a los filtros de chip (estatus/prioridad): de aquí
        # salen los conteos por chip que ve el frontend — si se calcularan
        # sobre `qs` ya filtrado por el chip activo, los DEMÁS chips
        # mostrarían siempre 0 en cuanto se selecciona uno (justo el bug
        # reportado). Sí respeta folio/search/scope de rol, para que los
        # conteos coincidan con la bandeja que el usuario está viendo.
        qs_sin_chip = qs

        # Mismos chips que arma ConsultarFUS.jsx (useEstatus('PARTICULAR'),
        # que en el backend trae PARTICULAR + AMBOS — ver EstatusListView):
        # catálogo activo de esos dos tipos, sin "Rechazado" (ahí no se
        # ofrece), más las dos temporalidades.
        claves_chip = list(
            Estatus.objects.filter(tipoFlujo__in=['PARTICULAR', 'AMBOS'], activa=True)
            .exclude(clave='Rechazado').values_list('clave', flat=True)
        ) + ['Vencido', 'PorVencer']
        conteos_estatus = {
            clave: qs_sin_chip.filter(_q_estatus_particular_fus(clave)).count()
            for clave in claves_chip
        }
        conteos_prioridad = {
            valor: qs_sin_chip.filter(prioridad=valor).count()
            for valor in ('Alta', 'Media', 'Baja')
        }

        if prioridad:
            qs = qs.filter(prioridad=prioridad)
        if estatus_raw:
            # Uno o varios chips a la vez (ej. "Registrado,Turnado") — se
            # combinan con OR, ya que un FUS solo puede estar en un estatus:
            # seleccionar varios amplía la bandeja, no la reduce a la
            # intersección (que siempre daría vacío salvo Vencido/PorVencer,
            # que son temporalidad y sí pueden convivir con un estatus).
            q_estatus = Q()
            for estatus in {e.strip() for e in estatus_raw.split(',') if e.strip()}:
                q_estatus |= _q_estatus_particular_fus(estatus)
            qs = qs.filter(q_estatus)

        qs = qs.order_by('-fechaRegistro')

        # Paginación
        try:
            page     = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 30))))
        except (ValueError, TypeError):
            page, page_size = 1, 30

        total  = qs.count()
        offset = (page - 1) * page_size
        pagina = list(qs[offset: offset + page_size])
        mapa   = mapa_correos_autorizados(emails_de_fus(pagina))
        data   = FUSSerializer(pagina, many=True, context={'mapa_correos': mapa}).data
        return Response({
            'total': total, 'page': page, 'page_size': page_size, 'results': data,
            'conteos': {'estatus': conteos_estatus, 'prioridad': conteos_prioridad},
        })

    def post(self, request):
        user  = request.user
        rol   = _rol(user)
        if rol not in ROLES_PARTICULAR:
            return Response({'detail': 'No autorizado.'}, status=403)

        propietario = _propietario_fus(user)
        if not propietario:
            return Response({'detail': 'No autorizado.'}, status=403)

        data  = request.data
        ip    = request.META.get('REMOTE_ADDR')
        now   = timezone.now()
        # Año en hora local, no UTC: México es UTC-6, así que un registro
        # entre ~18:00 y 23:59 hora local del 31 de diciembre ya cae en el
        # año siguiente en UTC y generaba folio del año equivocado (mismo
        # tipo de bug ya corregido para fechaLimite/Actividad).
        year  = timezone.localtime(now).year

        # El frontend ya exige estos tres campos antes de enviar el
        # formulario, pero el backend los aceptaba vacíos sin protestar
        # (cualquier llamada directa a la API podía crear un FUS sin medio
        # ni prioridad ni descripción real) — misma regla, del lado servidor.
        descripcion = data.get('descripcion', '').strip()
        if len(descripcion) < 20:
            return Response({'detail': 'La descripción debe tener al menos 20 caracteres.'}, status=400)

        medio_id = data.get('idMedioRecepcion')
        if not medio_id:
            return Response({'detail': 'Selecciona un medio de recepción.'}, status=400)
        medio = get_object_or_404(MedioRecepcion, pk=medio_id)

        if not data.get('prioridad'):
            return Response({'detail': 'Selecciona una prioridad.'}, status=400)

        nombre_ext = data.get('nombreExterno', '').strip() or None
        tel_ext    = data.get('telefonoExterno', '').strip() or None
        correo_ext = data.get('correoExterno', '').strip() or None

        from django.db import IntegrityError, transaction

        fus = None
        MAX_INTENTOS_FOLIO = 5
        for intento in range(MAX_INTENTOS_FOLIO):
            try:
                # El lock de generar_folio() (select_for_update) solo protege
                # mientras se mantenga la misma transacción real: antes vivía
                # en su propio `with transaction.atomic()` que hacía commit y
                # liberaba el lock ANTES del create() de abajo, dejando una
                # ventana donde dos altas simultáneas podían calcular el mismo
                # consecutivo. Envolver folio+create en un solo atomic (nested
                # atomic = savepoint de la misma transacción) cierra esa
                # ventana; el unique=True de FUS.folio sigue como red de
                # seguridad final vía el reintento.
                with transaction.atomic():
                    folio = generar_folio(rol, year)
                    fus = FUS.objects.create(
                        folio=folio,
                        idSolicitanteInterno=propietario,
                        fechaHora=now,
                        descripcion=descripcion,
                        contexto=data.get('contexto', ''),
                        idMedioRecepcion=medio,
                        medioEspecificacion=data.get('medioEspecificacion', ''),
                        prioridad=data.get('prioridad') or None,
                        criterios=data.get('criterios') or None,
                        nombreExterno=nombre_ext,
                        telefonoExterno=tel_ext,
                        correoExterno=correo_ext,
                        estatusParticular_id='Registrado',
                        idUsuarioRegistra=user.id,
                        fechaLimite=data.get('fechaLimite') or None,
                    )
                break
            except IntegrityError:
                if intento == MAX_INTENTOS_FOLIO - 1:
                    return Response(
                        {'detail': 'No se pudo generar el folio de la solicitud, intenta de nuevo.'},
                        status=status.HTTP_409_CONFLICT,
                    )
                continue

        fus.refresh_from_db()

        err_resp = guardar_evidencias(fus, request, user)
        if err_resp:
            fus.delete()
            return err_resp

        if fus.fechaLimite:
            # fus.fechaLimite viene del ORM en UTC — .date()/.time() directos
            # devuelven el día/hora en UTC, que puede caer un día antes o
            # después del que el usuario eligió (México es UTC-6). localtime()
            # lo convierte a hora de México antes de partirlo, para que un
            # límite de "hoy" quede en el calendario exactamente hoy.
            limite_local = timezone.localtime(fus.fechaLimite)
            Actividad.objects.create(
                titulo=f"Vence FUS: {fus.folio}",
                fecha=limite_local.date(),
                horaInicio=limite_local.time(),
                horaFin=limite_local.time(),
                tipo='limite',
                idCreador=user,
                idFusRelacionado=fus,
                activo=1,
            )

        _log(usuario=user.email, rol=rol, accion='REGISTRO_FUS',
             ip=ip, folio=folio, estado_nuevo='Registrado')

        return Response(FUSSerializer(fus).data, status=status.HTTP_201_CREATED)


class FUSDetailView(APIView):
    """GET / PATCH — ver o editar un FUS individual (ROL1). Solo editable en estatus 'Registrado'."""
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, pk):
        rol = _rol(request.user)
        if rol not in ROLES_PARTICULAR:
            return Response({'detail': 'No autorizado.'}, status=403)
        propietario = _propietario_fus(request.user)
        if not propietario:
            return Response({'detail': 'No autorizado.'}, status=403)
        fus = get_object_or_404(
            FUS.objects.select_related('idSolicitanteInterno', 'idMedioRecepcion').prefetch_related('evidencias'),
            pk=pk, activo=1, idSolicitanteInterno=propietario,
        )
        return Response(FUSSerializer(fus).data)

    def patch(self, request, pk):
        user = request.user
        rol  = _rol(user)
        if rol not in ROLES_PARTICULAR:
            return Response({'detail': 'No autorizado.'}, status=403)

        propietario = _propietario_fus(user)
        if not propietario:
            return Response({'detail': 'No autorizado.'}, status=403)

        fus = get_object_or_404(FUS, pk=pk, activo=1, idSolicitanteInterno=propietario)
        if fus.estatusParticular_id != 'Registrado':
            return Response(
                {'detail': 'Solo se puede editar una solicitud en estatus "Registrado".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Baja lógica de evidencias que el usuario quitó al editar, ANTES de
        # guardar_evidencias: así el tope de 30 MB por FUS (RN-09) ya cuenta
        # el espacio liberado al calcular si las nuevas evidencias caben.
        eliminar_evidencias(fus, request)

        # Se valida la evidencia ANTES de tocar cualquier campo del FUS: antes
        # se guardaba fus.save() y solo al final se validaba el archivo, así
        # que un archivo rechazado (tipo/tamaño inválido) dejaba los cambios
        # de texto ya persistidos en BD aunque la respuesta fuera un error.
        err_resp = guardar_evidencias(fus, request, user)
        if err_resp:
            return err_resp

        data = request.data
        if 'idMedioRecepcion' in data:
            medio_id = data.get('idMedioRecepcion')
            fus.idMedioRecepcion = get_object_or_404(MedioRecepcion, pk=medio_id) if medio_id else None
        if 'descripcion' in data:         fus.descripcion = data.get('descripcion', '')
        if 'contexto' in data:            fus.contexto = data.get('contexto', '')
        if 'medioEspecificacion' in data:  fus.medioEspecificacion = data.get('medioEspecificacion', '')
        if 'prioridad' in data:           fus.prioridad = data.get('prioridad') or None
        if 'criterios' in data:           fus.criterios = data.get('criterios') or None
        if 'nombreExterno' in data:       fus.nombreExterno = data.get('nombreExterno', '').strip() or None
        if 'telefonoExterno' in data:     fus.telefonoExterno = data.get('telefonoExterno', '').strip() or None
        if 'correoExterno' in data:       fus.correoExterno = data.get('correoExterno', '').strip() or None
        if 'fechaLimite' in data:         fus.fechaLimite = data.get('fechaLimite') or None
        fus.idUsuarioModifica = user.id
        fus.save()
        fus.refresh_from_db()

        if 'fechaLimite' in data:
            if fus.fechaLimite:
                # Igual que al registrar/turnar (ver comentario en el POST de
                # esta vista): localtime() antes de partir en fecha/hora, o un
                # límite de "hoy" puede quedar un día antes o después en el
                # calendario (México es UTC-6). update_or_create sin filtrar
                # por `activo` reutiliza el recordatorio existente (si lo
                # había) tanto para agregar la fecha límite por primera vez
                # como para reprogramarla.
                limite_local = timezone.localtime(fus.fechaLimite)
                Actividad.objects.update_or_create(
                    idFusRelacionado=fus, tipo='limite',
                    defaults={
                        'titulo': f"Vence FUS: {fus.folio}",
                        'fecha': limite_local.date(),
                        'horaInicio': limite_local.time(),
                        'horaFin': limite_local.time(),
                        'idCreador': user,
                        'activo': 1,
                    },
                )
            else:
                # Se quitó la fecha límite: el recordatorio deja de aplicar
                # (baja lógica, no se borra — mismo criterio que el resto del
                # calendario).
                Actividad.objects.filter(idFusRelacionado=fus, tipo='limite').update(activo=0)

        _log(usuario=user.email, rol=rol, accion='REGISTRO_FUS',
             ip=request.META.get('REMOTE_ADDR'), folio=fus.folio, obs='Edición de solicitud')

        return Response(FUSSerializer(fus).data)


class FUSDetalleAuditoriaView(APIView):
    """Detalle de auditoría visible únicamente para usuarios relacionados al FUS."""
    permission_classes = [IsAuthenticated]

    def get(self, request, folio):
        rol = _rol(request.user)
        if rol not in (*ROLES_PARTICULAR, 'ROL2'):
            return Response({'detail': 'No autorizado.'}, status=403)

        fus = get_object_or_404(
            FUS.objects.select_related('idSolicitanteInterno', 'idMedioRecepcion', 'estatusParticular'),
            folio=folio,
            activo=1,
        )
        if not _puede_ver_fus(request.user, fus):
            raise Http404

        turnados = Turnado.objects.filter(idFus=fus).select_related(
            'idDestinatario'
        ).prefetch_related('seguimientos').order_by('fechaHoraTurnado')
        if rol == 'ROL2':
            turnados = turnados.filter(idDestinatario=request.user, activo=1)

        seguimientos = []
        estatus_titular = None
        for t in turnados:
            estatus_titular = t.estatusTitular_id
            autor = (t.idDestinatario.first_name or t.idDestinatario.email) if t.idDestinatario else None
            for s in t.seguimientos.all():
                if not s.activo:
                    continue
                seguimientos.append({
                    'fecha': s.fechaActividad,
                    'autor': autor,
                    'texto': s.descripcionActividad,
                })

        # Respuestas del Comisionado (SeguimientoRespuesta) — feed aparte del
        # de Turnado/ROL2, se quedaban fuera del modal aunque el FUS sí
        # tuviera respuestas reales registradas (ej. cualquier FUS comisionado
        # directo, sin turnado de por medio).
        TIPO_SEG_LABEL = dict(SeguimientoRespuesta.TIPO_CHOICES)
        for s in fus.seguimientosComisionado.filter(activo=1).select_related('idAutor'):
            seguimientos.append({
                'fecha': s.fechaRegistro,
                'autor': resolver_nombre(s.idAutor) if s.idAutor else None,
                'texto': f'{TIPO_SEG_LABEL.get(s.tipo, s.tipo)}: {s.contenido}',
            })
        # Mezcla tipos no comparables entre sí: `fechaActividad` (Seguimiento,
        # DateField -> date), `fechaRegistro` (SeguimientoRespuesta,
        # DateTimeField -> datetime) y None en los seguimientos que el flujo
        # de validación por persona crea sin fecha (Atendido/Concluido/
        # Rechazado por el Particular, ver turnado.py) — ordenar directo por
        # `s['fecha']` truena con "'<' not supported between instances of
        # 'str' and 'datetime.date'" en cuanto un FUS mezcla ambos casos.
        # isoformat() normaliza todo a texto comparable sin perder el orden
        # cronológico real (None se va al principio, como antes).
        seguimientos.sort(key=lambda s: s['fecha'].isoformat() if s['fecha'] else '')

        sol = fus.idSolicitanteInterno
        return Response({
            'folio': fus.folio,
            'descripcion': fus.descripcion,
            'contexto': fus.contexto,
            'medioRecepcion': (
                f'{fus.idMedioRecepcion.nombreMedio} — {fus.medioEspecificacion}'
                if fus.idMedioRecepcion and fus.idMedioRecepcion.nombreMedio == 'Otro' and fus.medioEspecificacion
                else (fus.idMedioRecepcion.nombreMedio if fus.idMedioRecepcion else None)
            ),
            'prioridad': fus.prioridad,
            'criterios': fus.criterios,
            'nombreExterno': fus.nombreExterno,
            'telefonoExterno': fus.telefonoExterno,
            'correoExterno': fus.correoExterno,
            'estatusParticular': fus.estatusParticular_id,
            'estatusTitular': estatus_titular,
            'fechaRegistro': fus.fechaRegistro,
            'idSolicitanteInterno': {
                'nombre': resolver_nombre(sol) if sol else None,
                'email': sol.email if sol else None,
            },
            'evidencias': [{'nombreArchivo': e.nombreArchivo} for e in fus.evidencias.filter(activo=1)],
            'seguimientos': seguimientos,
        })


# ── Descargar evidencia (archivo adjunto de un FUS) ───────────────────────────

class DescargarEvidenciaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, evidencia_id):
        evidencia = get_object_or_404(Evidencia, pk=evidencia_id, activo=1)
        fus = evidencia.idFus
        if not _puede_ver_fus(request.user, fus):
            raise Http404

        # Defensa en profundidad: aunque rutaArchivo se genera con
        # os.path.basename() al subir el archivo (sin componentes de
        # directorio de por medio), se revalida aquí que la ruta resuelta
        # no se salga de MEDIA_ROOT antes de abrir el archivo.
        media_root = os.path.realpath(settings.MEDIA_ROOT)
        ruta = os.path.realpath(os.path.join(media_root, evidencia.rutaArchivo))
        if os.path.commonpath([media_root, ruta]) != media_root:
            raise Http404
        if not os.path.exists(ruta):
            raise Http404
        return FileResponse(open(ruta, 'rb'), as_attachment=True, filename=evidencia.nombreArchivo)


# ── Descargar FUS individual (PDF) ────────────────────────────────────────────

def generar_pdf_fus(fus, incluir_imagenes=False, rol_visor='ROL1', turnado_id=None, solo_destinatario_id=None):
    """Construye el PDF de un FUS (usado tanto para la descarga directa como
    para el adjunto en las notificaciones por correo). Devuelve los bytes.

    `rol_visor` determina qué ve cada quién, mismo criterio que la pantalla
    de detalle: 'ROL1' (incluye EQUIPO_PARTICULAR) ve la sección "Se turnó"
    y las respuestas como si las hubiera dado el Titular, sin exponer al
    comisionado. 'ROL2' no ve "Se turnó" (ya lo hizo él) pero sí a su
    comisionado real, con sus respuestas.

    `turnado_id`: si se da, acota "SE TURNÓ"/"RESPUESTA Y SEGUIMIENTO" a un
    solo destinatario en vez de todos — filtrar la lista de turnados aquí
    (antes de que ambas secciones la recorran) alcanza para las dos, sin
    tocar su lógica interna.

    `solo_destinatario_id`: cuando `rol_visor='ROL2'` este parámetro es la
    única fuente de verdad de qué turnados puede ver el llamante — se aplica
    SIEMPRE, sin importar `turnado_id` (que puede venir de un query param
    controlado por el cliente), para que un Titular nunca pueda pedir el PDF
    filtrado a un `turnado_id` que no es el suyo y ver así las respuestas de
    otro Titular en el mismo FUS."""
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, Image as RLImage, PageBreak, KeepTogether,
    )
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from xml.sax.saxutils import escape as _esc_xml
    import io

    def esc(valor):
        """Escapa &/</> antes de insertarlo en un Paragraph — ReportLab lee
        ese texto como marcado XML (negritas, <br/>, etc.), así que texto
        libre del usuario (descripción, contexto, comentarios, respuestas...)
        sin escapar rompe el parseo o, peor, se pierde en silencio (ReportLab
        descarta lo que interpreta como una etiqueta desconocida) — el PDF
        terminaba guardando información incompleta o corrupta sin ningún
        error visible. Ej.: 'Ref: A&B <confidencial>' quedaba truncado a
        'Ref: A&B;'."""
        return _esc_xml(str(valor)) if valor not in (None, '') else valor

    evidencias = [e for e in fus.evidencias.all() if e.activo]
    turnados = [t for t in fus.turnados.all() if t.activo]
    if solo_destinatario_id is not None:
        turnados = [t for t in turnados if t.idDestinatario_id == solo_destinatario_id]
    elif turnado_id:
        turnados = [t for t in turnados if str(t.id) == str(turnado_id)]

    LETTERHEAD_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'membretada.png')

    def _membrete(canvas_, doc_):
        canvas_.saveState()
        if os.path.exists(LETTERHEAD_PATH):
            canvas_.drawImage(
                LETTERHEAD_PATH, 0, 0,
                width=letter[0], height=letter[1],
                mask='auto', preserveAspectRatio=False,
            )
        canvas_.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=3.3*cm, bottomMargin=2.8*cm)
    W = letter[0] - 4*cm  # ancho útil

    VERDE    = colors.black
    AMARILLO = colors.HexColor("#FFFD78")  # antes '#FFFF00' — mismo ámbar que usa el resto del sistema, menos intenso
    CLARO    = colors.white
    BORDE    = colors.black

    st_titulo = ParagraphStyle('titulo', fontName='Helvetica-Bold', fontSize=16,
                               textColor=colors.black, spaceAfter=2)
    st_folio  = ParagraphStyle('folio',  fontName='Helvetica-Bold', fontSize=11,
                               textColor=colors.black, spaceBefore=6, spaceAfter=8)
    st_sec    = ParagraphStyle('sec',    fontName='Helvetica-Bold', fontSize=9,
                               textColor=colors.black, spaceAfter=0)
    st_lbl    = ParagraphStyle('lbl',    fontName='Helvetica-Bold', fontSize=8,
                               textColor=colors.black)
    st_val    = ParagraphStyle('val',    fontName='Helvetica',      fontSize=8,
                               textColor=colors.black, leading=11)

    fmt = lambda d: d.strftime('%d/%m/%Y %H:%M') if d else '—'

    sol = fus.idSolicitanteInterno
    nombre_sol = resolver_nombre(sol) if sol else '—'

    elements = []

    # ── Encabezado ──
    elements.append(Paragraph('FORMATO ÚNICO DE SOLICITUD', st_titulo))
    elements.append(Paragraph(
        f'Folio: {fus.folio} &nbsp;|&nbsp; Estatus: {fus.estatusParticular.nombre if fus.estatusParticular_id else "—"}',
        st_folio,
    ))
    elements.append(HRFlowable(width='100%', thickness=2, color=VERDE, spaceAfter=10))

    def seccion(titulo):
        t = Table([[Paragraph(titulo, st_sec)]], colWidths=[W])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), AMARILLO),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ]))
        return t

    def fila(lbl, val):
        return [Paragraph(lbl, st_lbl), Paragraph(esc(val) if val else '—', st_val)]

    # ── Datos generales ──
    medio_recepcion = (
        f'{fus.idMedioRecepcion.nombreMedio} — {fus.medioEspecificacion}'
        if fus.idMedioRecepcion and fus.idMedioRecepcion.nombreMedio == 'Otro' and fus.medioEspecificacion
        else (fus.idMedioRecepcion.nombreMedio if fus.idMedioRecepcion else '—')
    )
    datos = [
        fila('Fecha y hora',        fmt(fus.fechaHora)),
        fila('Medio de recepción',  medio_recepcion),
        fila('Solicitante interno', nombre_sol),
    ]
    dt = Table(datos, colWidths=[4*cm, W - 4*cm])
    dt.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, CLARO]),
        ('GRID',           (0,0), (-1,-1), 0.3, BORDE),
        ('TOPPADDING',     (0,0), (-1,-1), 4),
        ('BOTTOMPADDING',  (0,0), (-1,-1), 4),
        ('LEFTPADDING',    (0,0), (-1,-1), 6),
        ('RIGHTPADDING',   (0,0), (-1,-1), 6),
    ]))
    elements.append(KeepTogether([seccion('DATOS GENERALES'), Spacer(1, 4), dt]))
    elements.append(Spacer(1, 8))

    # ── Descripción ──
    desc_data = [
        fila('Descripción', fus.descripcion),
        fila('Datos o antecedentes de contexto de la solicitud', fus.contexto or '—'),
    ]
    dt2 = Table(desc_data, colWidths=[4*cm, W - 4*cm])
    dt2.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, CLARO]),
        ('GRID',           (0,0), (-1,-1), 0.3, BORDE),
        ('TOPPADDING',     (0,0), (-1,-1), 6),
        ('BOTTOMPADDING',  (0,0), (-1,-1), 6),
        ('LEFTPADDING',    (0,0), (-1,-1), 6),
        ('RIGHTPADDING',   (0,0), (-1,-1), 6),
        ('VALIGN',         (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(KeepTogether([seccion('DESCRIPCIÓN DE LA SOLICITUD'), Spacer(1, 4), dt2]))
    elements.append(Spacer(1, 8))

    # ── Solicitante externo ──
    if fus.nombreExterno or fus.correoExterno or fus.telefonoExterno:
        ext_data = [
            fila('Nombre',    fus.nombreExterno),
            fila('Correo',    fus.correoExterno),
            fila('Teléfono',  fus.telefonoExterno),
        ]
        dt3 = Table(ext_data, colWidths=[4*cm, W - 4*cm])
        dt3.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, CLARO]),
            ('GRID',           (0,0), (-1,-1), 0.3, BORDE),
            ('TOPPADDING',     (0,0), (-1,-1), 4),
            ('BOTTOMPADDING',  (0,0), (-1,-1), 4),
            ('LEFTPADDING',    (0,0), (-1,-1), 6),
            ('RIGHTPADDING',   (0,0), (-1,-1), 6),
        ]))
        elements.append(KeepTogether([seccion('SOLICITANTE EXTERNO'), Spacer(1, 4), dt3]))
        elements.append(Spacer(1, 8))

    # ── Evidencia (solo nombres de archivo; las imágenes van al final si se solicitaron) ──
    if evidencias:
        ev_rows = []
        for ev in evidencias:
            texto = esc(ev.nombreArchivo) if ev.nombreArchivo else '—'
            if ev.comentarios:
                texto += f' — {esc(ev.comentarios)}'
            ev_rows.append([Paragraph(texto, st_val)])
        evt = Table(ev_rows, colWidths=[W])
        evt.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, CLARO]),
            ('GRID',           (0,0), (-1,-1), 0.3, BORDE),
            ('TOPPADDING',     (0,0), (-1,-1), 5),
            ('BOTTOMPADDING',  (0,0), (-1,-1), 5),
            ('LEFTPADDING',    (0,0), (-1,-1), 8),
        ]))
        elements.append(KeepTogether([seccion('EVIDENCIA'), Spacer(1, 4), evt]))
    else:
        elements.append(KeepTogether([seccion('EVIDENCIA'), Spacer(1, 4), Paragraph('—', st_val)]))
    elements.append(Spacer(1, 8))

    # ── Prioridad ──
    prioridad_bloque = [seccion('PRIORIDAD'), Spacer(1, 4), Paragraph(f'<b>{esc(fus.prioridad) if fus.prioridad else "—"}</b>', st_val)]
    if fus.criterios:
        prioridad_bloque.append(Spacer(1, 2))
        for crit in [c.strip() for c in fus.criterios.split('|') if c.strip()]:
            prioridad_bloque.append(Paragraph(f'• {esc(crit)}', st_val))
    elements.append(KeepTogether(prioridad_bloque))
    elements.append(Spacer(1, 8))

    TIPO_SEG_LABEL = dict(SeguimientoRespuesta.TIPO_CHOICES)

    # Marcadores de auditoría que se crean solos al marcar un turnado como
    # Atendido/Concluido/Rechazado (ver MarcarTurnadoAtendidoView/
    # ConcluirPersonaTurnadoView/RechazarPersonaTurnadoView) — quedan en la
    # misma tabla Seguimiento que las respuestas reales que la persona
    # escribe, pero no son una respuesta; en el PDF, "RESPUESTA Y
    # SEGUIMIENTO" debe mostrar solo lo segundo.
    ACCION_PREFIJOS = ('Atendido:', 'Concluido por el Particular.', 'Rechazado por ')

    def _es_respuesta_real(seguimiento):
        return not (seguimiento.descripcionActividad or '').startswith(ACCION_PREFIJOS)

    def _tabla_seg(rows, col1=3*cm):
        t = Table(rows, colWidths=[col1, W - col1])
        t.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, CLARO]),
            ('GRID',           (0,0), (-1,-1), 0.3, BORDE),
            ('TOPPADDING',     (0,0), (-1,-1), 4),
            ('BOTTOMPADDING',  (0,0), (-1,-1), 4),
            ('LEFTPADDING',    (0,0), (-1,-1), 6),
            ('RIGHTPADDING',   (0,0), (-1,-1), 6),
            ('VALIGN',         (0,0), (-1,-1), 'TOP'),
        ]))
        return t

    respuestas_comisionado = list(
        fus.seguimientosComisionado.exclude(tipo='rechazo').order_by('fechaRegistro')
    ) if fus.idComisionado_id else []

    if rol_visor == 'ROL2':
        # Rol 2 ya turnó él mismo — no tiene sentido mostrárselo. En cambio
        # ve a su comisionado real (si lo hay) y sus respuestas, sin disfraz.
        if fus.idComisionado_id:
            com = fus.idComisionado
            com_data = [
                fila('Nombre',     resolver_nombre(com)),
                fila('Correo',     com.email),
                fila('Dirección',  _resolver_unidad_administrativa(com) or '—'),
            ]
            elements.append(KeepTogether([seccion('COMISIONADO'), Spacer(1, 4), _tabla_seg(com_data, col1=4*cm)]))
            elements.append(Spacer(1, 8))

            if respuestas_comisionado:
                seg_rows = [
                    [Paragraph(s.fechaRegistro.strftime('%d/%m/%Y %H:%M'), st_val),
                     Paragraph(f'<b>{TIPO_SEG_LABEL.get(s.tipo, s.tipo)}:</b> {esc(s.contenido)}', st_val)]
                    for s in respuestas_comisionado
                ]
                elements.append(KeepTogether([seccion('RESPUESTA Y SEGUIMIENTO'), Spacer(1, 4), _tabla_seg(seg_rows)]))
            else:
                elements.append(KeepTogether([
                    seccion('RESPUESTA Y SEGUIMIENTO'), Spacer(1, 4),
                    Paragraph('El comisionado aún no ha registrado respuestas.', st_val),
                ]))
            elements.append(Spacer(1, 8))
        elif turnados:
            # Sin comisionado: el flujo directo, con sus propias respuestas.
            turnados_con_seguimiento = [(t, [s for s in t.seguimientos.all() if s.activo and _es_respuesta_real(s)]) for t in turnados]
            turnados_con_seguimiento = [(t, segs) for t, segs in turnados_con_seguimiento if segs]
            if turnados_con_seguimiento:
                for i, (t, segs) in enumerate(turnados_con_seguimiento):
                    seg_rows = []
                    for s in segs:
                        fecha_str = s.fechaActividad.strftime('%d/%m/%Y') if s.fechaActividad else '—'
                        texto = esc(s.descripcionActividad) if s.descripcionActividad else '—'
                        if s.accionTexto:
                            texto += f'<br/>→ {esc(s.accionTexto)}'
                        seg_rows.append([Paragraph(fecha_str, st_val), Paragraph(texto, st_val)])
                    bloque = [_tabla_seg(seg_rows)] if i > 0 else [seccion('RESPUESTA Y SEGUIMIENTO'), Spacer(1, 4), _tabla_seg(seg_rows)]
                    elements.append(KeepTogether(bloque))
                    elements.append(Spacer(1, 8))
            else:
                elements.append(KeepTogether([
                    seccion('RESPUESTA Y SEGUIMIENTO'), Spacer(1, 4),
                    Paragraph('Pendiente de respuesta.', st_val),
                ]))
                elements.append(Spacer(1, 8))

    else:  # ROL1 (incluye EQUIPO_PARTICULAR): ve "Se turnó" y las respuestas
           # como si las hubiera dado el Titular, sin exponer al comisionado.
        if turnados:
            for i, t in enumerate(turnados):
                dest_nombre = resolver_nombre(t.idDestinatario) if t.idDestinatario else '—'
                medio_envio = (
                    f'{t.idMedio.nombreMedio} — {t.medioEspecificacion}'
                    if t.idMedio and t.idMedio.nombreMedio == 'Otro' and t.medioEspecificacion
                    else (t.idMedio.nombreMedio if t.idMedio else '—')
                )
                turno_data = [
                    fila('Nombre',             dest_nombre),
                    fila('Medio de envío',     medio_envio),
                    fila('Fecha y hora',       fmt(t.fechaHoraTurnado)),
                    fila('Texto de la solicitud', t.solicitudTexto or '—'),
                ]
                bloque = [seccion('SE TURNÓ'), Spacer(1, 4), _tabla_seg(turno_data, col1=4*cm)] if i == 0 else [_tabla_seg(turno_data, col1=4*cm)]
                elements.append(KeepTogether(bloque))
                elements.append(Spacer(1, 6))

            algun_bloque = False
            for t in turnados:
                dest_nombre = resolver_nombre(t.idDestinatario) if t.idDestinatario else '—'
                propias = [s for s in t.seguimientos.all() if s.activo and _es_respuesta_real(s)]
                seg_rows = [
                    [Paragraph(s.fechaActividad.strftime('%d/%m/%Y') if s.fechaActividad else '—', st_val),
                     Paragraph((esc(s.descripcionActividad) if s.descripcionActividad else '—') + (f'<br/>→ {esc(s.accionTexto)}' if s.accionTexto else ''), st_val)]
                    for s in propias
                ]
                seg_rows += [
                    [Paragraph(s.fechaRegistro.strftime('%d/%m/%Y'), st_val),
                     Paragraph(f'<b>{TIPO_SEG_LABEL.get(s.tipo, s.tipo)}:</b> {esc(s.contenido)}', st_val)]
                    for s in respuestas_comisionado
                ]
                if not seg_rows:
                    continue
                bloque = [Paragraph(esc(dest_nombre), st_lbl), Spacer(1, 2), _tabla_seg(seg_rows)]
                if not algun_bloque:
                    bloque = [seccion('RESPUESTA Y SEGUIMIENTO'), Spacer(1, 4)] + bloque
                    algun_bloque = True
                elements.append(KeepTogether(bloque))
                elements.append(Spacer(1, 8))

            if not algun_bloque:
                elements.append(KeepTogether([
                    seccion('RESPUESTA Y SEGUIMIENTO'), Spacer(1, 4),
                    Paragraph('Pendiente de respuesta del titular.', st_val),
                ]))
                elements.append(Spacer(1, 8))

    # ── Pie ──
    elements.append(Spacer(1, 12))
    elements.append(HRFlowable(width='100%', thickness=0.5, color=BORDE))
    pie = ParagraphStyle('pie', fontName='Helvetica', fontSize=7,
                         textColor=colors.HexColor('#888888'), spaceBefore=4)
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
    elements.append(Paragraph(
        f'Agencia Nacional de Aduanas de México — Sistema de Control de Solicitudes — Generado: {now_str}',
        pie
    ))

    # ── Anexo de imágenes de evidencia (hoja nueva, al final) ──
    if incluir_imagenes:
        imagenes = [e for e in evidencias if (e.tipoMime or '').startswith('image/')]
        rutas_validas = []
        for ev in imagenes:
            ruta_abs = os.path.join(settings.MEDIA_ROOT, ev.rutaArchivo or '')
            if ev.rutaArchivo and os.path.exists(ruta_abs):
                rutas_validas.append((ev, ruta_abs))

        if rutas_validas:
            elements.append(PageBreak())
            elements.append(Paragraph('ANEXO — IMÁGENES DE EVIDENCIA', st_titulo))
            elements.append(HRFlowable(width='100%', thickness=2, color=VERDE, spaceAfter=12))
            max_w, max_h = W, 20*cm
            for ev, ruta_abs in rutas_validas:
                elements.append(Paragraph(esc(ev.nombreArchivo) if ev.nombreArchivo else '—', st_lbl))
                elements.append(Spacer(1, 4))
                try:
                    img = RLImage(ruta_abs)
                    ratio = min(max_w / img.imageWidth, max_h / img.imageHeight, 1)
                    img.drawWidth  = img.imageWidth * ratio
                    img.drawHeight = img.imageHeight * ratio
                    elements.append(img)
                except Exception:
                    elements.append(Paragraph('(No se pudo cargar la imagen)', st_val))
                elements.append(Spacer(1, 16))

    doc.build(elements, onFirstPage=_membrete, onLaterPages=_membrete)
    return buf.getvalue()


class DescargarFUSPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, folio):
        from django.http import HttpResponse
        try:
            fus = FUS.objects.select_related(
                'idSolicitanteInterno', 'idMedioRecepcion', 'estatusParticular'
            ).prefetch_related(
                'evidencias', 'turnados__idDestinatario', 'turnados__idMedio', 'turnados__seguimientos'
            ).get(folio=folio, activo=1)
        except FUS.DoesNotExist:
            from rest_framework.response import Response
            return Response({'detail': 'FUS no encontrado.'}, status=404)

        rol = _rol(request.user)
        # Mismo criterio de visibilidad que FUSListCreateView: Rol 1 ve y
        # descarga cualquier FUS (es quien está más arriba en la jerarquía,
        # no solo los que él mismo registró). Equipo del Particular queda
        # acotado al Rol 1 que lo dio de alta, y Rol 2 a los FUS que le
        # turnaron a él específicamente.
        if rol == 'ROL1':
            autorizado = True
        elif rol == 'EQUIPO_PARTICULAR':
            autorizado = _propietario_fus(request.user) == fus.idSolicitanteInterno
        elif rol == 'ROL2':
            autorizado = Turnado.objects.filter(idFus=fus, idDestinatario=request.user, activo=1).exists()
        else:
            autorizado = False
        if not autorizado:
            from rest_framework.response import Response
            return Response({'detail': 'No autorizado.'}, status=403)

        rol_visor = 'ROL2' if rol == 'ROL2' else 'ROL1'
        incluir_imagenes = request.query_params.get('imagenes') == '1'
        turnado_id = request.query_params.get('turnado_id') or None
        # Un Titular (ROL2) solo puede ver sus propios turnados: se ignora
        # cualquier `turnado_id` que venga del cliente y se fuerza el filtro
        # por su propio usuario, para que no pueda pedir el PDF de la parte
        # de otro Titular en el mismo FUS (ver docstring de generar_pdf_fus).
        solo_destinatario_id = request.user.id if rol == 'ROL2' else None
        pdf_bytes = generar_pdf_fus(
            fus, incluir_imagenes=incluir_imagenes, rol_visor=rol_visor,
            turnado_id=turnado_id, solo_destinatario_id=solo_destinatario_id,
        )
        resp = HttpResponse(pdf_bytes, content_type='application/pdf')
        nombre = fus.folio.replace('/', '-')
        resp['Content-Disposition'] = f'attachment; filename="FUS_{nombre}.pdf"'
        return resp
