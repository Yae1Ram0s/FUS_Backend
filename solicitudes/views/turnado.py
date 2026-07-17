from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from autenticacion.models import CorreoAutorizado
from catalogos.models import MedioRecepcion
from ..models import FUS, Turnado, Seguimiento, Notificacion, Actividad
from ..serializers import TurnadoSerializer, TurnadoActividadSerializer, SeguimientoSerializer
from ..utils import resolver_nombre
from ..helpers import notificar_por_correo
from .helpers import _rol, _log, ROLES_PARTICULAR, _propietario_fus


def _push_notificacion(notif):
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    group_name = f'notificaciones_{notif.idDestinatario_id}'
    data = {
        'id':            str(notif.id),
        'fusFolio':      notif.fusFolio,
        'tipo':          notif.tipoEvento,
        'mensaje':       notif.mensaje,
        'leida':         False,
        'fechaCreacion': notif.fechaGeneracion.isoformat(),
    }
    async_to_sync(channel_layer.group_send)(
        group_name,
        {'type': 'nueva_notificacion', 'data': data},
    )


class TurnarFUSView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        rol  = _rol(user)
        if rol not in ROLES_PARTICULAR:
            return Response({'detail': 'No autorizado.'}, status=403)

        propietario = _propietario_fus(user)
        if not propietario:
            return Response({'detail': 'No autorizado.'}, status=403)

        fus           = get_object_or_404(FUS, pk=pk, activo=1, idSolicitanteInterno=propietario)
        ip            = request.META.get('REMOTE_ADDR')
        destinatarios = request.data.get('destinatarios', [])
        solicitud_txt = request.data.get('solicitudTexto', '')
        now           = timezone.now()

        if not destinatarios:
            return Response({'detail': 'Se requiere al menos un destinatario.'}, status=400)

        # Solo se puede turnar si el FUS está en Registrado o Turnado
        if fus.estatusParticular_id not in ('Registrado', 'Turnado'):
            return Response(
                {'detail': f'No se puede turnar un FUS en estado "{fus.estatusParticular_id}".'},
                status=400,
            )

        # Nombre del remitente (ROL1) para las notificaciones
        remitente_auth = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
        nombre_remitente = remitente_auth.nombre if remitente_auth else (user.first_name or user.email)

        for dest in destinatarios:
            dest_user = get_object_or_404(User, pk=dest['idDestinatario'])
            if _rol(dest_user) != 'ROL2':
                return Response({'detail': 'Destinatario inválido: debe ser un usuario ROL2 activo.'}, status=400)
            medio     = get_object_or_404(MedioRecepcion, pk=dest['idMedio'])

            ya_turnado = Turnado.objects.filter(idFus=fus, idDestinatario=dest_user, activo=1).exclude(estatusTitular_id='Concluido').exists()
            if ya_turnado:
                continue  # ya tiene un turnado activo, no duplicar

            Turnado.objects.create(
                idFus=fus,
                idRemitente=user,
                idDestinatario=dest_user,
                idMedio=medio,
                solicitudTexto=solicitud_txt,
                fechaHoraTurnado=now,
                idUsuarioRegistra=user.id,
            )
            if fus.fechaLimite:
                actividad_limite, _creada = Actividad.objects.get_or_create(
                    idFusRelacionado=fus, tipo='limite', activo=1,
                    defaults={
                        'titulo': f"Vence FUS: {fus.folio}",
                        'fecha': fus.fechaLimite.date(),
                        'horaInicio': fus.fechaLimite.time(),
                        'horaFin': fus.fechaLimite.time(),
                        'idCreador': user,
                    },
                )
                actividad_limite.participantes.add(dest_user)

            _notif = Notificacion.objects.create(
                idDestinatario=dest_user,
                fusFolio=fus.folio,
                tipoEvento='TURNADO',
                mensaje=f"{nombre_remitente} te ha turnado el FUS {fus.folio}.",
            )
            _push_notificacion(_notif)
            notificar_por_correo(_notif)

        estado_ant = fus.estatusParticular_id
        fus.estatusParticular_id = 'Turnado'
        fus.idUsuarioModifica = user.id
        fus.save()

        _log(usuario=user.email, rol=rol, accion='TURNAR_FUS',
             ip=ip, folio=fus.folio, estado_ant=estado_ant, estado_nuevo='Turnado')

        return Response({'detail': 'FUS turnado correctamente.'})


# ── Actividad de un FUS (ROL1 solo lectura) ──────────────────────────────────

class FUSActividadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if _rol(request.user) not in ROLES_PARTICULAR:
            return Response({'detail': 'No autorizado.'}, status=403)

        propietario = _propietario_fus(request.user)
        if not propietario:
            return Response({'detail': 'No autorizado.'}, status=403)

        fus = get_object_or_404(FUS, pk=pk, activo=1, idSolicitanteInterno=propietario)
        turnados = Turnado.objects.filter(
            idFus=fus, activo=1
        ).select_related(
            'idDestinatario', 'idRemitente', 'idMedio',
        ).prefetch_related(
            'seguimientos',
        ).order_by('fechaHoraTurnado')
        return Response(TurnadoActividadSerializer(turnados, many=True).data)


class FUSTrazabilidadView(APIView):
    """Línea de tiempo de un FUS (creación + turnados/respuestas). Sin restricción
    de dueño a nivel de FUS: la usan tanto Consultar FUS como Bitácora, y en
    Bitácora un ROL1 audita folios que no necesariamente son suyos.

    ROL2 solo ve su propia porción: el turnado que le corresponde a él (no los
    de otros destinatarios) y sus respuestas/conclusión — nada de creación,
    que es anterior a que el asunto le llegara."""
    permission_classes = [IsAuthenticated]

    def get(self, request, folio):
        fus = get_object_or_404(FUS, folio=folio, activo=1)
        rol = _rol(request.user)

        eventos = []

        turnados_qs = Turnado.objects.filter(idFus=fus, activo=1).select_related(
            'idDestinatario'
        ).prefetch_related('seguimientos')

        if rol == 'ROL2':
            turnados_qs = turnados_qs.filter(idDestinatario=request.user)
        elif fus.fechaRegistro:
            eventos.append({
                'tipo':    'creacion',
                'fecha':   fus.fechaRegistro,
                'actor':   resolver_nombre(fus.idSolicitanteInterno) if fus.idSolicitanteInterno else None,
                'detalle': 'Solicitud registrada',
            })

        turnados = list(turnados_qs.order_by('fechaHoraTurnado'))

        for t in turnados:
            actor = resolver_nombre(t.idDestinatario) if t.idDestinatario else None
            if t.fechaHoraTurnado:
                eventos.append({
                    'tipo':    'turnado',
                    'fecha':   t.fechaHoraTurnado,
                    'actor':   actor,
                    'detalle': f'Turnado a {actor}' if actor else 'Turnado',
                })

            segs = [s for s in t.seguimientos.all() if s.activo]
            for i, s in enumerate(segs):
                es_final = i == len(segs) - 1
                tipo = 'concluido' if (es_final and t.estatusTitular_id == 'Concluido') else 'respuesta'
                eventos.append({
                    'tipo':    tipo,
                    'fecha':   s.fechaRegistro,
                    'actor':   actor,
                    'detalle': s.descripcionActividad,
                })

        eventos.sort(key=lambda e: e['fecha'])

        # Estado actual — para el punto "en vivo" del timeline. ROL2 ve el
        # estatus de su propio turnado (más reciente); ROL1 ve el estatus
        # general del FUS.
        if rol == 'ROL2':
            estatus_actual = turnados[-1].estatusTitular_id if turnados else None
        else:
            estatus_actual = fus.estatusParticular_id

        return Response({'folio': fus.folio, 'eventos': eventos, 'estatusActual': estatus_actual})


# ── Turnados (ROL2) ──────────────────────────────────────────────────────────

class MisTurnadosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Turnado.objects.filter(
            idDestinatario=request.user, activo=1
        ).select_related(
            'idFus', 'idFus__idSolicitanteInterno', 'idFus__idMedioRecepcion',
            'idRemitente', 'idMedio',
        )

        estatus = request.query_params.get('estatusTitular')
        search  = request.query_params.get('search')
        if estatus == 'Vencido':
            qs = qs.filter(idFus__estatusParticular_id='Turnado', idFus__fechaLimite__lt=timezone.now())
        elif estatus == 'PorVencer':
            from datetime import timedelta
            ahora = timezone.now()
            qs = qs.filter(
                idFus__estatusParticular_id='Turnado',
                idFus__fechaLimite__gte=ahora,
                idFus__fechaLimite__lte=ahora + timedelta(hours=24),
            )
        elif estatus:
            qs = qs.filter(estatusTitular_id=estatus)
        if search:
            emails_nombre = list(CorreoAutorizado.objects.filter(nombre__icontains=search).values_list('email', flat=True))
            qs = qs.filter(
                Q(idFus__folio__icontains=search) |
                Q(idFus__descripcion__icontains=search) |
                Q(idFus__contexto__icontains=search) |
                Q(idFus__medioEspecificacion__icontains=search) |
                Q(idFus__criterios__icontains=search) |
                Q(idFus__nombreExterno__icontains=search) |
                Q(idFus__telefonoExterno__icontains=search) |
                Q(idFus__correoExterno__icontains=search) |
                Q(idFus__idMedioRecepcion__nombreMedio__icontains=search) |
                Q(idFus__idSolicitanteInterno__email__icontains=search) |
                Q(idFus__idSolicitanteInterno__email__in=emails_nombre) |
                Q(idFus__evidencias__nombreArchivo__icontains=search) |
                Q(idFus__evidencias__comentarios__icontains=search) |
                Q(solicitudTexto__icontains=search) |
                Q(idMedio__nombreMedio__icontains=search) |
                Q(idRemitente__email__icontains=search) |
                Q(idRemitente__email__in=emails_nombre) |
                Q(idDestinatario__email__icontains=search) |
                Q(idDestinatario__email__in=emails_nombre) |
                Q(seguimientos__descripcionActividad__icontains=search) |
                Q(seguimientos__accionTexto__icontains=search)
            ).distinct()

        qs = qs.order_by('-fechaRegistro')

        # Paginación
        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 30))))
        except (ValueError, TypeError):
            page, page_size = 1, 30

        total  = qs.count()
        offset = (page - 1) * page_size
        data   = TurnadoSerializer(qs[offset: offset + page_size], many=True).data
        return Response({'total': total, 'page': page, 'page_size': page_size, 'results': data})


class ConcluirTurnadoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        turnado = get_object_or_404(Turnado, pk=pk, activo=1, idDestinatario=request.user)

        if turnado.estatusTitular_id == 'Concluido':
            return Response({'detail': 'El asunto ya está concluido.'}, status=400)

        # Condición obligatoria: debe existir al menos una respuesta registrada
        tiene_respuestas = Seguimiento.objects.filter(idTurnado=turnado, activo=1).exists()
        if not tiene_respuestas:
            return Response(
                {'detail': 'Debes registrar al menos una respuesta de seguimiento antes de concluir el asunto.'},
                status=400,
            )

        user    = request.user
        ip      = request.META.get('REMOTE_ADDR')
        rol     = _rol(user)
        est_ant = turnado.estatusTitular_id

        turnado.estatusTitular_id    = 'Concluido'
        turnado.idUsuarioModifica = user.id
        turnado.save()

        _log(usuario=user.email, rol=rol, accion='CONCLUSION_FUS',
             ip=ip, folio=turnado.idFus.folio,
             estado_ant=est_ant, estado_nuevo='Concluido')

        # Si TODOS los turnados activos del FUS están concluidos → FUS pasa a Concluido
        fus        = turnado.idFus
        pendientes = fus.turnados.filter(activo=1).exclude(estatusTitular_id='Concluido').count()
        if pendientes == 0:
            est_ant_fus              = fus.estatusParticular_id
            fus.estatusParticular_id = 'Concluido'
            fus.fechaConclusion   = timezone.now()
            fus.idUsuarioModifica = user.id
            fus.save()

            concluye_auth = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
            nombre_concluye = concluye_auth.nombre if concluye_auth else (user.first_name or user.email)
            _notif = Notificacion.objects.create(
                idDestinatario=fus.idSolicitanteInterno,
                fusFolio=fus.folio,
                tipoEvento='CONCLUIDO',
                mensaje=f"{nombre_concluye} ha concluido el FUS {fus.folio}.",
            )
            _push_notificacion(_notif)
            notificar_por_correo(_notif)

            _log(usuario=user.email, rol=rol, accion='ASIGNACION_ESTADO',
                 ip=ip, folio=fus.folio,
                 estado_ant=est_ant_fus, estado_nuevo='Concluido')

        return Response({'detail': 'Asunto concluido correctamente.'})


# ── Seguimientos ─────────────────────────────────────────────────────────────

class SeguimientoListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, turnado_id):
        turnado = get_object_or_404(Turnado, pk=turnado_id, activo=1)
        if turnado.idDestinatario_id != request.user.id:
            return Response({'detail': 'No autorizado.'}, status=403)
        qs      = Seguimiento.objects.filter(idTurnado=turnado, activo=1).order_by('fechaRegistro')
        return Response(SeguimientoSerializer(qs, many=True).data)

    def post(self, request, turnado_id):
        turnado = get_object_or_404(Turnado, pk=turnado_id, activo=1)
        if turnado.idDestinatario_id != request.user.id:
            return Response({'detail': 'No autorizado.'}, status=403)

        # Guard: bloquear si el asunto ya está concluido
        if turnado.estatusTitular_id == 'Concluido':
            return Response(
                {'detail': 'No se pueden agregar respuestas a un asunto ya concluido.'},
                status=400,
            )

        user = request.user
        ip   = request.META.get('REMOTE_ADDR')
        rol  = _rol(user)

        seg = Seguimiento.objects.create(
            idTurnado=turnado,
            fechaActividad=request.data.get('fechaActividad') or None,
            descripcionActividad=request.data.get('descripcionActividad', ''),
            accionTexto=request.data.get('accionTexto') or None,
            idUsuarioRegistra=user.id,
        )

        # Nombre del titular (ROL2) para las notificaciones
        titular_auth = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
        nombre_titular = titular_auth.nombre if titular_auth else (user.first_name or user.email)

        fus = turnado.idFus

        # Transición Recibido → En_seguimiento (primera respuesta del titular)
        if turnado.estatusTitular_id == 'Recibido':
            turnado.estatusTitular_id = 'En_seguimiento'
            turnado.idUsuarioModifica = user.id
            turnado.save()

            # Transición FUS: Turnado → Atendido (cuando al menos un titular responde)
            if fus.estatusParticular_id == 'Turnado':
                fus.estatusParticular_id = 'Atendido'
                fus.idUsuarioModifica = user.id
                fus.save()

                _notif = Notificacion.objects.create(
                    idDestinatario=fus.idSolicitanteInterno,
                    fusFolio=fus.folio,
                    tipoEvento='CAMBIO_ESTADO',
                    mensaje=f"{nombre_titular} comenzó a atender el FUS {fus.folio}.",
                )
                _push_notificacion(_notif)
                notificar_por_correo(_notif)

                _log(usuario=user.email, rol=rol, accion='ASIGNACION_ESTADO',
                     ip=ip, folio=fus.folio,
                     estado_ant='Turnado', estado_nuevo='Atendido',
                     obs=f'Primera respuesta registrada por {nombre_titular}')
        else:
            # Seguimientos posteriores — notificar al ROL1 cada nueva respuesta
            resumen = seg.descripcionActividad[:80]
            if len(seg.descripcionActividad) > 80:
                resumen += '…'
            _notif = Notificacion.objects.create(
                idDestinatario=fus.idSolicitanteInterno,
                fusFolio=fus.folio,
                tipoEvento='RESPUESTA',
                mensaje=f"{nombre_titular} registró una nueva respuesta en el FUS {fus.folio}: \"{resumen}\"",
            )
            _push_notificacion(_notif)
            notificar_por_correo(_notif)

        _log(usuario=user.email, rol=rol, accion='REGISTRO_RESPUESTA',
             ip=ip, folio=fus.folio)

        return Response(SeguimientoSerializer(seg).data, status=status.HTTP_201_CREATED)


class SeguimientoDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        seg = get_object_or_404(Seguimiento, pk=pk, activo=1)
        if seg.idTurnado.idDestinatario_id != request.user.id:
            return Response({'detail': 'No autorizado.'}, status=403)

        # Guard: bloquear si el asunto está concluido
        if seg.idTurnado.estatusTitular_id == 'Concluido':
            return Response(
                {'detail': 'No se pueden eliminar respuestas de un asunto ya concluido.'},
                status=400,
            )

        seg.activo = 0
        seg.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
