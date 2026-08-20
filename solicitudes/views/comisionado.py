from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from autenticacion.models import CorreoAutorizado
from ..models import FUS, Actividad, Bitacora, Notificacion, SeguimientoRespuesta
from ..serializers import (
    FUSSerializer, SeguimientoRespuestaSerializer, SeguimientoComisionadoCreateSerializer,
    ComisionarFUSSerializer, AtendidoFUSSerializer, ConcluirAsuntoSerializer, RechazarSolicitudSerializer,
)
from ..permissions import (
    _unidad_id,
    EsRol1oRol2, EsRol1oTurnadoDestinatario, EsRol1DuenoDelFUS,
    EsComisionado, EsComisionadoAsignado, PuedeVerSeguimientoComisionado,
)
from ..services import notificar_por_correo, notificar_por_correo_lote, push_notificacion
from ..utils import _equipo_particular_de
from ..helpers import emails_de_fus, mapa_correos_autorizados
from .helpers import _rol, _log, _primer_error


def _particulares_area(unidad_id):
    emails = CorreoAutorizado.objects.filter(
        rol='ROL1', activo=1, unidadAdministrativa_id=unidad_id
    ).values_list('email', flat=True)
    return User.objects.filter(email__in=emails, is_active=True)


def _quien_comisiono(fus):
    """Usuario (ROL1/ROL2) que ejecutó `comisionar` sobre este FUS, resuelto a
    partir de la bitácora — no hay campo dedicado en el modelo FUS."""
    entrada = Bitacora.objects.filter(
        fusFolio=fus.folio, accion='ASIGNACION_COMISIONADO'
    ).order_by('-fechaHora').first()
    if not entrada:
        return None
    return User.objects.filter(email=entrada.usuario, is_active=True).first()


class FUSComisionadosDisponiblesView(APIView):
    """GET — usuarios rol=COMISIONADO de la misma unidad administrativa que el
    usuario autenticado (ROL1 o ROL2, ambos con facultad de comisionar)."""
    permission_classes = [IsAuthenticated, EsRol1oRol2]

    def get(self, request, pk):
        fus = get_object_or_404(FUS, pk=pk, activo=1)
        self.check_object_permissions(request, fus)

        qs = CorreoAutorizado.objects.select_related('unidadAdministrativa').filter(
            rol='COMISIONADO', activo=1, unidadAdministrativa_id=_unidad_id(request.user)
        )
        q = request.query_params.get('q')
        if q:
            qs = qs.filter(Q(nombre__icontains=q) | Q(email__icontains=q))

        usuarios_por_email = {
            u.email: u.id for u in User.objects.filter(email__in=qs.values_list('email', flat=True), is_active=True)
        }
        data = [
            {
                'id': usuarios_por_email[ca.email],
                'nombre': ca.nombre,
                'email': ca.email,
                'direccion': ca.unidadAdministrativa.unidadAdministrativa if ca.unidadAdministrativa_id else None,
            }
            for ca in qs if ca.email in usuarios_por_email
        ]
        return Response(data)


class ComisionarFUSView(APIView):
    permission_classes = [IsAuthenticated, EsRol1oTurnadoDestinatario]

    @transaction.atomic
    def post(self, request, pk):
        fus = get_object_or_404(FUS.objects.select_for_update(), pk=pk, activo=1)
        self.check_object_permissions(request, fus)

        ser = ComisionarFUSSerializer(data=request.data, context={'request': request, 'fus': fus})
        if not ser.is_valid():
            return Response({'detail': _primer_error(ser)}, status=400)

        user        = request.user
        rol         = _rol(user)
        comisionado = ser.validated_data['comisionado']
        turnado     = ser.validated_data['turnado']
        ip          = request.META.get('REMOTE_ADDR')
        est_ant     = fus.estatusParticular_id

        with transaction.atomic():
            fus.idComisionado = comisionado
            fus.fechaAsignacion = timezone.now()
            fus.estatusParticular_id = 'En_seguimiento'
            fus.idUsuarioModifica = user.id
            fus.save()

            if turnado:
                turnado.estatusTitular_id = 'En_seguimiento'
                turnado.idUsuarioModifica = user.id
                turnado.save()

            if fus.fechaLimite:
                # Mismo criterio que TurnarFUSView (turnado.py): el
                # comisionado se suma como participante del recordatorio
                # "Vence FUS" del calendario — sin esto, la temporalidad del
                # FUS (fecha límite, vencido/por vencer) solo la veía quien lo
                # registró/turnó, nunca el comisionado que de verdad lo
                # atiende. get_or_create reutiliza la Actividad si ya existía
                # (creada al registrar o al turnar el FUS).
                limite_local = timezone.localtime(fus.fechaLimite)
                actividad_limite, _creada = Actividad.objects.get_or_create(
                    idFusRelacionado=fus, tipo='limite', activo=1,
                    defaults={
                        'titulo': f"Vence FUS: {fus.folio}",
                        'fecha': limite_local.date(),
                        'horaInicio': limite_local.time(),
                        'horaFin': limite_local.time(),
                        'idCreador': user,
                    },
                )
                actividad_limite.participantes.add(comisionado)

            _log(usuario=user.email, rol=rol, accion='ASIGNACION_COMISIONADO',
                 ip=ip, folio=fus.folio, estado_ant=est_ant, estado_nuevo='En_seguimiento')

            asignador_auth = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
            nombre_asignador = asignador_auth.nombre if asignador_auth else (user.first_name or user.email)
            notif = Notificacion.objects.create(
                idDestinatario=comisionado,
                fusFolio=fus.folio,
                tipoEvento='ASIGNADO_COMISIONADO',
                mensaje=f"{nombre_asignador} te asignó el FUS {fus.folio} para su seguimiento.",
            )

        push_notificacion(notif)
        notificar_por_correo(notif)

        return Response(FUSSerializer(fus).data)


class MisFUSComisionadosView(APIView):
    """GET — FUS asignados al Comisionado autenticado (alimenta su Calendario)."""
    permission_classes = [IsAuthenticated, EsComisionado]

    def get(self, request):
        qs = FUS.objects.filter(idComisionado=request.user, activo=1).select_related(
            'idSolicitanteInterno', 'idMedioRecepcion', 'idComisionado'
        ).prefetch_related('evidencias', 'turnados__idDestinatario').order_by('-fechaAsignacion')

        search = request.query_params.get('search')
        if search:
            qs = qs.filter(Q(folio__icontains=search) | Q(descripcion__icontains=search))

        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 30))))
        except (ValueError, TypeError):
            page, page_size = 1, 30

        total  = qs.count()
        offset = (page - 1) * page_size
        pagina = list(qs[offset: offset + page_size])
        mapa   = mapa_correos_autorizados(emails_de_fus(pagina))
        data   = FUSSerializer(pagina, many=True, context={'mapa_correos': mapa}).data
        return Response({'total': total, 'page': page, 'page_size': page_size, 'results': data})


class SeguimientoComisionadoListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), EsComisionadoAsignado()]
        return [IsAuthenticated(), PuedeVerSeguimientoComisionado()]

    def get(self, request, pk):
        fus = get_object_or_404(FUS, pk=pk, activo=1)
        self.check_object_permissions(request, fus)

        qs = SeguimientoRespuesta.objects.filter(idFus=fus, activo=1).select_related('idAutor').order_by('fechaRegistro')
        return Response(SeguimientoRespuestaSerializer(qs, many=True).data)

    def post(self, request, pk):
        fus = get_object_or_404(FUS, pk=pk, activo=1)
        self.check_object_permissions(request, fus)

        ser = SeguimientoComisionadoCreateSerializer(data=request.data, context={'fus': fus})
        ser.is_valid(raise_exception=True)
        descripcion = ser.validated_data['descripcionActividad']
        accion_texto = ser.validated_data['accionTexto']
        fecha_actividad = ser.validated_data.get('fechaActividad')

        user = request.user
        with transaction.atomic():
            # 'avance' si trae descripción (con o sin acción); si solo trae
            # acción por emprender, el tag que se le muestra al Particular es
            # 'accion_por_emprender' — mismo criterio de una sola etiqueta por
            # entrada que ya usaba el selector manual que este flujo reemplaza.
            tipo = 'avance' if descripcion else 'accion_por_emprender'
            seg = SeguimientoRespuesta.objects.create(
                idFus=fus, idAutor=user, tipo=tipo, contenido=descripcion,
                accionTexto=accion_texto, fechaActividad=fecha_actividad,
            )

            _log(usuario=user.email, rol=_rol(user), accion='SEGUIMIENTO_COMISIONADO',
                 ip=request.META.get('REMOTE_ADDR'), folio=fus.folio)

            # Respuesta que "activa" el FUS -> Atendido: la primera tras ser
            # comisionado (En_seguimiento) o la primera tras un rechazo
            # (Rechazado — ya no se reabre solo con consultar, hace falta que
            # el comisionado vuelva a responder). select_for_update evita que
            # dos respuestas casi simultáneas disparen la transición dos veces.
            fus_lock = FUS.objects.select_for_update().get(pk=fus.pk)
            notificaciones = []
            if fus_lock.estatusParticular_id in ('En_seguimiento', 'Rechazado'):
                est_ant = fus_lock.estatusParticular_id
                fus_lock.estatusParticular_id = 'Atendido'
                fus_lock.idUsuarioModifica = user.id
                fus_lock.save()

                accion = 'REAPERTURA_FUS' if est_ant == 'Rechazado' else 'ASIGNACION_ESTADO'
                _log(usuario=user.email, rol=_rol(user), accion=accion,
                     ip=request.META.get('REMOTE_ADDR'), folio=fus.folio,
                     estado_ant=est_ant, estado_nuevo='Atendido')

                # Si el rechazo había reflejado 'Rechazado' en Turnado.estatusTitular
                # (ver RechazarSolicitudView), esta reapertura lo regresa a
                # 'En_seguimiento' — mismo estatus con el que arrancó el turnado, ya
                # que el Titular vuelve a tener seguimiento pendiente del comisionado.
                if est_ant == 'Rechazado':
                    fus.turnados.filter(activo=1, estatusTitular_id='Rechazado').update(
                        estatusTitular_id='En_seguimiento', idUsuarioModifica=user.id
                    )

                # Sin esto, nadie se enteraba en vivo de que el comisionado ya
                # atendió el FUS — mismo criterio de destinatarios que
                # AtendidoFUSView (Rol 1 de la unidad del comisionado, que
                # pueden compartir supervisión, MÁS el dueño real del FUS).
                # El dueño se agrega siempre, no solo cuando no hay
                # comisionado: si el FUS llegó al comisionado vía un Turnado a
                # otra unidad (el Titular delegó en vez de responder directo),
                # `_particulares_area(_unidad_id(fus.idComisionado))` resuelve
                # la unidad del comisionado, no la del dueño original, y este
                # último se quedaba sin avisar aunque el FUS siguiera siendo
                # suyo.
                destinatarios = set(
                    _particulares_area(_unidad_id(fus.idComisionado)) if fus.idComisionado_id else []
                )
                if fus.idSolicitanteInterno_id:
                    destinatarios.add(fus.idSolicitanteInterno)
                destinatarios |= set(_equipo_particular_de(fus.idSolicitanteInterno))
                # Si el FUS llegó al comisionado vía un Turnado (el Titular lo
                # delegó en vez de responder directo), esa persona también se
                # entera de que el comisionado ya empezó a atenderlo — antes
                # solo se avisaba al lado del Particular (dueño del FUS + su
                # unidad/equipo), dejando al Titular que delegó sin ninguna señal.
                destinatarios |= {
                    t.idDestinatario for t in fus.turnados.filter(activo=1) if t.idDestinatario_id
                }
                destinatarios.discard(user)

                # Si quien comisionó fue Rol 2 (el Titular delegó en vez de
                # responder directo), el aviso a Rol 1 se firma con el nombre
                # de ese Rol 2 en vez de "El comisionado" — de cara al
                # Particular, el responsable sigue siendo el Titular que
                # delegó, no la identidad interna del Comisionado. Si quien
                # comisionó fue el propio Rol 1 (se comisiona a sí mismo un
                # FUS que ya es suyo), no aplica: se quedaría notificando a
                # alguien de su nombre propio.
                comisionador = _quien_comisiono(fus)
                mensaje = f"El comisionado atendió el FUS {fus.folio}."
                if comisionador and _rol(comisionador) == 'ROL2':
                    ca_comisiono = CorreoAutorizado.objects.filter(email=comisionador.email, activo=1).first()
                    nombre_comisiono = ca_comisiono.nombre if ca_comisiono else (comisionador.first_name or comisionador.email)
                    mensaje = f"{nombre_comisiono} comenzó a atender el FUS {fus.folio}."

                notificaciones = [
                    Notificacion.objects.create(
                        idDestinatario=particular,
                        fusFolio=fus.folio,
                        tipoEvento='SEGUIMIENTO_FINALIZADO',
                        mensaje=mensaje,
                    )
                    for particular in destinatarios
                ]

        for notif in notificaciones:
            push_notificacion(notif)
        notificar_por_correo_lote(notificaciones)

        return Response(SeguimientoRespuestaSerializer(seg).data, status=201)


class AtendidoFUSView(APIView):
    """POST — el comisionado terminó su seguimiento; pasa la solicitud a
    validación del Particular. Lo puede disparar Rol 1, o Rol 2 destinatario
    específico del Turnado de este FUS (no el propio comisionado, ni
    cualquier Rol 2 de la dirección)."""
    permission_classes = [IsAuthenticated, EsRol1oTurnadoDestinatario]

    @transaction.atomic
    def post(self, request, pk):
        fus = get_object_or_404(FUS.objects.select_for_update(), pk=pk, activo=1)
        self.check_object_permissions(request, fus)

        ser = AtendidoFUSSerializer(data=request.data, context={'fus': fus})
        if not ser.is_valid():
            return Response({'detail': _primer_error(ser)}, status=400)

        user    = request.user
        rol     = _rol(user)
        ip      = request.META.get('REMOTE_ADDR')
        est_ant = fus.estatusParticular_id

        with transaction.atomic():
            fus.estatusParticular_id = 'Pendiente_validacion'
            fus.idUsuarioModifica = user.id
            fus.save()

            # Mismo espejo que Concluir/Rechazar: sin esto, Turnado.estatusTitular
            # se queda pegado en "En_seguimiento" para el Titular aunque el FUS ya
            # esté Pendiente de validación.
            fus.turnados.filter(activo=1).exclude(estatusTitular_id='Pendiente_validacion').update(
                estatusTitular_id='Pendiente_validacion', idUsuarioModifica=user.id
            )

            _log(usuario=user.email, rol=rol, accion='ATENCION_FUS',
                 ip=ip, folio=fus.folio, estado_ant=est_ant, estado_nuevo='Pendiente_validacion')

            # Con comisionado: se notifica a todos los Rol 1 de su unidad (varios
            # pueden compartir supervisión) MÁS el dueño real del FUS — este
            # último se agrega siempre, no solo cuando no hay comisionado: si
            # el FUS llegó al comisionado vía un Turnado a otra unidad (el
            # Titular delegó en vez de responder directo), la unidad del
            # comisionado no es la del dueño original, y se quedaba sin avisar
            # aunque el FUS siguiera siendo suyo. Más su(s) asistente(s)
            # EQUIPO_PARTICULAR, que comparten esa misma pantalla.
            destinatarios = set(
                _particulares_area(_unidad_id(fus.idComisionado)) if fus.idComisionado_id else []
            )
            if fus.idSolicitanteInterno_id:
                destinatarios.add(fus.idSolicitanteInterno)
            destinatarios |= set(_equipo_particular_de(fus.idSolicitanteInterno))
            # Mismo criterio que SeguimientoComisionadoListCreateView.post: si el
            # FUS llegó al comisionado vía un Turnado, ese Titular también se
            # entera de que ya se mandó a validación — antes solo se avisaba al
            # lado del Particular.
            destinatarios |= {
                t.idDestinatario for t in fus.turnados.filter(activo=1) if t.idDestinatario_id
            }
            destinatarios.discard(user)
            notificaciones = [
                Notificacion.objects.create(
                    idDestinatario=particular,
                    fusFolio=fus.folio,
                    tipoEvento='SEGUIMIENTO_FINALIZADO',
                    mensaje=f"El seguimiento del FUS {fus.folio} fue atendido y está pendiente de tu validación.",
                )
                for particular in destinatarios
            ]

        for notif in notificaciones:
            push_notificacion(notif)
        notificar_por_correo_lote(notificaciones)

        return Response(FUSSerializer(fus).data)


class ConcluirAsuntoView(APIView):
    """POST — validación final positiva. Exclusivo del Particular (ROL1) de
    la dirección del comisionado asignado."""
    permission_classes = [IsAuthenticated, EsRol1DuenoDelFUS]

    @transaction.atomic
    def post(self, request, pk):
        fus = get_object_or_404(FUS.objects.select_for_update(), pk=pk, activo=1)
        self.check_object_permissions(request, fus)

        ser = ConcluirAsuntoSerializer(data=request.data, context={'fus': fus})
        if not ser.is_valid():
            return Response({'detail': _primer_error(ser)}, status=400)

        user    = request.user
        ip      = request.META.get('REMOTE_ADDR')
        est_ant = fus.estatusParticular_id
        comisionador = _quien_comisiono(fus)

        with transaction.atomic():
            fus.estatusParticular_id = 'Concluido'
            fus.fechaConclusion = timezone.now()
            fus.idUsuarioModifica = user.id
            fus.save()

            # Si el FUS se turnó antes de comisionarse, Turnado.estatusTitular
            # es el estatus que ve el Titular (Rol 2) en Solicitudes Turnadas
            # — vive aparte de FUS.estatusParticular y hay que reflejarlo aquí
            # también, o se queda pegado en "En_seguimiento" para siempre.
            fus.turnados.filter(activo=1).exclude(estatusTitular_id='Concluido').update(
                estatusTitular_id='Concluido', idUsuarioModifica=user.id
            )

            _log(usuario=user.email, rol=_rol(user), accion='APROBACION_FUS',
                 ip=ip, folio=fus.folio, estado_ant=est_ant, estado_nuevo='Concluido')

            # Sin comisionado ni `comisionador` (Rol 2 respondió directo, nadie
            # comisionó), el set quedaba vacío y Rol 2 nunca se enteraba de la
            # conclusión salvo refrescando — se agrega también el destinatario
            # de cada turnado activo, el dueño del FUS y su(s) asistente(s)
            # EQUIPO_PARTICULAR, sin auto-notificar a quien acaba de concluir.
            destinatarios = {u for u in (fus.idComisionado, comisionador) if u}
            for turnado in fus.turnados.filter(activo=1).select_related('idDestinatario'):
                if turnado.idDestinatario_id:
                    destinatarios.add(turnado.idDestinatario)
            if fus.idSolicitanteInterno_id:
                destinatarios.add(fus.idSolicitanteInterno)
            destinatarios |= set(_equipo_particular_de(fus.idSolicitanteInterno))
            destinatarios.discard(user)

            notificaciones = [
                Notificacion.objects.create(
                    idDestinatario=destinatario,
                    fusFolio=fus.folio,
                    tipoEvento='SOLICITUD_APROBADA',
                    mensaje=f"El FUS {fus.folio} fue aprobado y la solicitud fue concluida.",
                )
                for destinatario in destinatarios
            ]

        for notif in notificaciones:
            push_notificacion(notif)
        notificar_por_correo_lote(notificaciones)

        return Response(FUSSerializer(fus).data)


class RechazarSolicitudView(APIView):
    """POST {motivo} — validación final negativa: NO regresa directo a
    seguimiento, queda visible en "Rechazado" hasta que el comisionado
    registre una nueva respuesta (ver SeguimientoComisionadoListCreateView.post,
    que en ese momento la reabre directo a "Atendido") — ya no se reabre solo
    con que alguien la consulte. Exclusivo del Particular (ROL1) dueño de
    este FUS."""
    permission_classes = [IsAuthenticated, EsRol1DuenoDelFUS]

    @transaction.atomic
    def post(self, request, pk):
        fus = get_object_or_404(FUS.objects.select_for_update(), pk=pk, activo=1)
        self.check_object_permissions(request, fus)

        ser = RechazarSolicitudSerializer(data=request.data, context={'fus': fus})
        if not ser.is_valid():
            return Response({'detail': _primer_error(ser)}, status=400)

        motivo  = ser.validated_data['motivo']
        user    = request.user
        ip      = request.META.get('REMOTE_ADDR')
        est_ant = fus.estatusParticular_id
        comisionador = _quien_comisiono(fus)

        with transaction.atomic():
            fus.estatusParticular_id = 'Rechazado'
            fus.idUsuarioModifica = user.id
            fus.save()

            # Mismo espejo que en ConcluirAsuntoView: sin esto, Turnado.estatusTitular
            # se queda pegado en "En_seguimiento" para el Titular aunque el FUS ya
            # esté Rechazado.
            fus.turnados.filter(activo=1).exclude(estatusTitular_id='Rechazado').update(
                estatusTitular_id='Rechazado', idUsuarioModifica=user.id
            )

            SeguimientoRespuesta.objects.create(idFus=fus, idAutor=user, tipo='rechazo', contenido=motivo)

            _log(usuario=user.email, rol=_rol(user), accion='RECHAZO_FUS',
                 ip=ip, folio=fus.folio, estado_ant=est_ant, estado_nuevo='Rechazado', obs=motivo)

            # `comisionador` es quien ejecutó "Comisionar" (Rol 1 o Rol 2), no el
            # comisionado en sí — a diferencia de ConcluirAsuntoView, aquí nunca
            # se notificaba al comisionado directamente, así que su pantalla
            # (FUSComisionados) no reabría el formulario de respuesta hasta
            # refrescar. Si el FUS nunca tuvo comisionado (Rol 2 respondió
            # directo), `comisionador` queda None y antes nadie se enteraba del
            # rechazo salvo refrescando — se agrega también el destinatario de
            # cada turnado activo, el dueño del FUS y su(s) asistente(s)
            # EQUIPO_PARTICULAR (comparten la misma pantalla que él), sin
            # duplicar y sin auto-notificar a quien acaba de rechazar.
            destinatarios = set()
            if comisionador:
                destinatarios.add(comisionador)
            if fus.idComisionado_id:
                destinatarios.add(fus.idComisionado)
            for turnado in fus.turnados.filter(activo=1).select_related('idDestinatario'):
                if turnado.idDestinatario_id:
                    destinatarios.add(turnado.idDestinatario)
            if fus.idSolicitanteInterno_id:
                destinatarios.add(fus.idSolicitanteInterno)
            destinatarios |= set(_equipo_particular_de(fus.idSolicitanteInterno))
            destinatarios.discard(user)

            notificaciones = [
                Notificacion.objects.create(
                    idDestinatario=dest,
                    fusFolio=fus.folio,
                    tipoEvento='SOLICITUD_RECHAZADA',
                    mensaje=f"El FUS {fus.folio} fue rechazado: {motivo}. Vuelve a consultarlo para reabrirlo a seguimiento.",
                )
                for dest in destinatarios
            ]

        for notif in notificaciones:
            push_notificacion(notif)
        notificar_por_correo_lote(notificaciones)

        return Response(FUSSerializer(fus).data)
