import hashlib
import os

from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from autenticacion.models import CorreoAutorizado
from catalogos.models import MedioRecepcion
from .models import FUS, SolicitanteExterno, Evidencia, Turnado, Seguimiento, Accion, Bitacora, Notificacion
from .serializers import FUSSerializer, TurnadoSerializer, TurnadoActividadSerializer, SeguimientoSerializer, AccionSerializer, NotificacionSerializer


# ── Helpers ─────────────────────────────────────────────────────────────────

def _rol(user):
    autorizado = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
    return autorizado.rol if autorizado else ''


def _log(usuario, rol, accion, ip=None, folio=None, estado_ant=None, estado_nuevo=None, obs=None):
    Bitacora.objects.create(
        fusFolio=folio,
        usuario=usuario,
        rol=rol,
        accion=accion,
        estadoAnterior=estado_ant,
        estadoNuevo=estado_nuevo,
        ipCliente=ip,
        observaciones=obs,
    )


def _generar_folio(rol, year):
    seq = FUS.objects.filter(fechaRegistro__year=year).count() + 1
    return f"ANAM/{rol}/FUS/{seq:04d}/{year}"


def _sha256(f):
    h = hashlib.sha256()
    for chunk in f.chunks():
        h.update(chunk)
    return h.hexdigest()


# ── FUS ─────────────────────────────────────────────────────────────────────

class FUSListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        qs = FUS.objects.filter(activo=1).select_related(
            'idSolicitanteInterno', 'idMedioRecepcion'
        ).prefetch_related('evidencias', 'solicitante_externo')

        estatus = request.query_params.get('estatusParticular')
        search  = request.query_params.get('search')
        if estatus:
            qs = qs.filter(estatusParticular=estatus)
        if search:
            qs = qs.filter(folio__icontains=search) | qs.filter(descripcion__icontains=search)

        qs = qs.order_by('-fechaRegistro')
        return Response(FUSSerializer(qs, many=True).data)

    def post(self, request):
        data  = request.data
        user  = request.user
        ip    = request.META.get('REMOTE_ADDR')
        rol   = _rol(user)
        now   = timezone.now()
        year  = now.year
        folio = _generar_folio(rol, year)

        medio_id = data.get('idMedioRecepcion')
        medio    = get_object_or_404(MedioRecepcion, pk=medio_id) if medio_id else None

        fus = FUS.objects.create(
            folio=folio,
            idSolicitanteInterno=user,
            fechaHora=now,
            descripcion=data.get('descripcion', ''),
            contexto=data.get('contexto', ''),
            idMedioRecepcion=medio,
            medioEspecificacion=data.get('medioEspecificacion', ''),
            prioridad=data.get('prioridad') or None,
            estatusParticular='Registrado',
            idUsuarioRegistra=user.id,
        )

        # Solicitante externo
        nombre_ext = data.get('nombreExterno', '').strip()
        tel_ext    = data.get('telefonoExterno', '').strip()
        correo_ext = data.get('correoExterno', '').strip()
        if nombre_ext or tel_ext or correo_ext:
            SolicitanteExterno.objects.create(
                idFus=fus,
                nombre=nombre_ext or None,
                telefono=tel_ext or None,
                correo=correo_ext or None,
                idUsuarioRegistra=user.id,
            )

        # Evidencias
        from django.conf import settings
        for archivo in request.FILES.getlist('evidencias'):
            sha = _sha256(archivo)
            ruta_rel = f"evidencias/{fus.pk}/{archivo.name}"
            ruta_abs = os.path.join(settings.MEDIA_ROOT, ruta_rel)
            os.makedirs(os.path.dirname(ruta_abs), exist_ok=True)
            with open(ruta_abs, 'wb') as dest:
                for chunk in archivo.chunks():
                    dest.write(chunk)
            Evidencia.objects.create(
                idFus=fus,
                nombreArchivo=archivo.name,
                rutaArchivo=ruta_rel,
                tipoMime=archivo.content_type,
                hashSha256=sha,
                idUsuarioRegistra=user.id,
            )

        _log(usuario=user.email, rol=rol, accion='REGISTRO_FUS',
             ip=ip, folio=folio, estado_nuevo='Registrado')

        return Response(FUSSerializer(fus).data, status=status.HTTP_201_CREATED)


class TurnarFUSView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        fus           = get_object_or_404(FUS, pk=pk, activo=1)
        user          = request.user
        ip            = request.META.get('REMOTE_ADDR')
        rol           = _rol(user)
        destinatarios = request.data.get('destinatarios', [])
        solicitud_txt = request.data.get('solicitudTexto', '')
        now           = timezone.now()

        if not destinatarios:
            return Response({'detail': 'Se requiere al menos un destinatario.'}, status=400)

        # Solo se puede turnar si el FUS está en Registrado o Turnado
        if fus.estatusParticular not in ('Registrado', 'Turnado'):
            return Response(
                {'detail': f'No se puede turnar un FUS en estado "{fus.estatusParticular}".'},
                status=400,
            )

        for dest in destinatarios:
            dest_user = get_object_or_404(User, pk=dest['idDestinatario'])
            medio     = get_object_or_404(MedioRecepcion, pk=dest['idMedio'])
            Turnado.objects.create(
                idFus=fus,
                idRemitente=user,
                idDestinatario=dest_user,
                idMedio=medio,
                solicitudTexto=solicitud_txt,
                fechaHoraTurnado=now,
                idUsuarioRegistra=user.id,
            )
            Notificacion.objects.create(
                idDestinatario=dest_user,
                fusFolio=fus.folio,
                tipoEvento='TURNADO',
                mensaje=f"Se te ha turnado el FUS {fus.folio}.",
            )

        estado_ant = fus.estatusParticular
        fus.estatusParticular = 'Turnado'
        fus.idUsuarioModifica = user.id
        fus.save()

        _log(usuario=user.email, rol=rol, accion='TURNAR_FUS',
             ip=ip, folio=fus.folio, estado_ant=estado_ant, estado_nuevo='Turnado')

        return Response({'detail': 'FUS turnado correctamente.'})


# ── Actividad de un FUS (ROL1 solo lectura) ──────────────────────────────────

class FUSActividadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        fus = get_object_or_404(FUS, pk=pk, activo=1)
        turnados = Turnado.objects.filter(
            idFus=fus, activo=1
        ).select_related(
            'idDestinatario', 'idRemitente', 'idMedio',
        ).prefetch_related(
            'seguimientos', 'acciones',
        ).order_by('fechaHoraTurnado')
        return Response(TurnadoActividadSerializer(turnados, many=True).data)


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
        if estatus:
            qs = qs.filter(estatusTitular=estatus)
        if search:
            qs = qs.filter(idFus__folio__icontains=search) | qs.filter(idFus__descripcion__icontains=search)

        qs = qs.order_by('-fechaRegistro')
        return Response(TurnadoSerializer(qs, many=True).data)


class ConcluirTurnadoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        turnado = get_object_or_404(Turnado, pk=pk, activo=1, idDestinatario=request.user)

        if turnado.estatusTitular == 'Concluido':
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
        est_ant = turnado.estatusTitular

        turnado.estatusTitular    = 'Concluido'
        turnado.idUsuarioModifica = user.id
        turnado.save()

        _log(usuario=user.email, rol=rol, accion='CONCLUSION_FUS',
             ip=ip, folio=turnado.idFus.folio,
             estado_ant=est_ant, estado_nuevo='Concluido')

        # Si TODOS los turnados activos del FUS están concluidos → FUS pasa a Concluido
        fus        = turnado.idFus
        pendientes = fus.turnados.filter(activo=1).exclude(estatusTitular='Concluido').count()
        if pendientes == 0:
            est_ant_fus           = fus.estatusParticular
            fus.estatusParticular = 'Concluido'
            fus.fechaConclusion   = timezone.now()
            fus.idUsuarioModifica = user.id
            fus.save()

            Notificacion.objects.create(
                idDestinatario=fus.idSolicitanteInterno,
                fusFolio=fus.folio,
                tipoEvento='CONCLUIDO',
                mensaje=f"El FUS {fus.folio} ha sido concluido por todos los titulares.",
            )

            _log(usuario=user.email, rol=rol, accion='ASIGNACION_ESTADO',
                 ip=ip, folio=fus.folio,
                 estado_ant=est_ant_fus, estado_nuevo='Concluido')

        return Response({'detail': 'Asunto concluido correctamente.'})


# ── Seguimientos ─────────────────────────────────────────────────────────────

class SeguimientoListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, turnado_id):
        turnado = get_object_or_404(Turnado, pk=turnado_id, activo=1)
        qs      = Seguimiento.objects.filter(idTurnado=turnado, activo=1).order_by('fechaActividad')
        return Response(SeguimientoSerializer(qs, many=True).data)

    def post(self, request, turnado_id):
        turnado = get_object_or_404(Turnado, pk=turnado_id, activo=1)

        # Guard: bloquear si el asunto ya está concluido
        if turnado.estatusTitular == 'Concluido':
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

        # Transición Recibido → En_seguimiento (primera respuesta del titular)
        if turnado.estatusTitular == 'Recibido':
            turnado.estatusTitular    = 'En_seguimiento'
            turnado.idUsuarioModifica = user.id
            turnado.save()

            # Transición FUS: Turnado → Atendido (cuando al menos un titular responde)
            fus = turnado.idFus
            if fus.estatusParticular == 'Turnado':
                fus.estatusParticular = 'Atendido'
                fus.idUsuarioModifica = user.id
                fus.save()

                Notificacion.objects.create(
                    idDestinatario=fus.idSolicitanteInterno,
                    fusFolio=fus.folio,
                    tipoEvento='CAMBIO_ESTADO',
                    mensaje=f"El FUS {fus.folio} está siendo atendido por el titular.",
                )

                _log(usuario=user.email, rol=rol, accion='ASIGNACION_ESTADO',
                     ip=ip, folio=fus.folio,
                     estado_ant='Turnado', estado_nuevo='Atendido',
                     obs='Primera respuesta registrada por titular')

        _log(usuario=user.email, rol=rol, accion='REGISTRO_RESPUESTA',
             ip=ip, folio=turnado.idFus.folio)

        return Response(SeguimientoSerializer(seg).data, status=status.HTTP_201_CREATED)


class SeguimientoDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        seg = get_object_or_404(Seguimiento, pk=pk, activo=1)

        # Guard: bloquear si el asunto está concluido
        if seg.idTurnado.estatusTitular == 'Concluido':
            return Response(
                {'detail': 'No se pueden eliminar respuestas de un asunto ya concluido.'},
                status=400,
            )

        seg.activo = 0
        seg.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Acciones ─────────────────────────────────────────────────────────────────

class AccionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, turnado_id):
        turnado = get_object_or_404(Turnado, pk=turnado_id, activo=1)
        qs      = Accion.objects.filter(idTurnado=turnado, activo=1).order_by('numeroOrden')
        return Response(AccionSerializer(qs, many=True).data)

    def post(self, request, turnado_id):
        turnado = get_object_or_404(Turnado, pk=turnado_id, activo=1)

        # Guard: bloquear si el asunto está concluido
        if turnado.estatusTitular == 'Concluido':
            return Response(
                {'detail': 'No se pueden agregar acciones a un asunto ya concluido.'},
                status=400,
            )

        user   = request.user
        ip     = request.META.get('REMOTE_ADDR')
        rol    = _rol(user)
        ultimo = Accion.objects.filter(idTurnado=turnado, activo=1).count()
        accion = Accion.objects.create(
            idTurnado=turnado,
            numeroOrden=ultimo + 1,
            descripcion=request.data.get('descripcion', ''),
            idUsuarioRegistra=user.id,
        )

        _log(usuario=user.email, rol=rol, accion='REGISTRO_ACCION',
             ip=ip, folio=turnado.idFus.folio)

        return Response(AccionSerializer(accion).data, status=status.HTTP_201_CREATED)


class AccionUpdateDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        accion = get_object_or_404(Accion, pk=pk, activo=1)

        # Guard: bloquear si el asunto está concluido
        if accion.idTurnado.estatusTitular == 'Concluido':
            return Response(
                {'detail': 'No se pueden modificar acciones de un asunto ya concluido.'},
                status=400,
            )

        if 'completada' in request.data:
            accion.completada = int(request.data['completada'])
        if 'descripcion' in request.data:
            accion.descripcion = request.data['descripcion']
        accion.idUsuarioModifica = request.user.id
        accion.save()
        return Response(AccionSerializer(accion).data)

    def delete(self, request, pk):
        accion = get_object_or_404(Accion, pk=pk, activo=1)

        # Guard: bloquear si el asunto está concluido
        if accion.idTurnado.estatusTitular == 'Concluido':
            return Response(
                {'detail': 'No se pueden eliminar acciones de un asunto ya concluido.'},
                status=400,
            )

        accion.activo = 0
        accion.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Notificaciones ────────────────────────────────────────────────────────────

class NotificacionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notificacion.objects.filter(
            idDestinatario=request.user
        ).order_by('-fechaGeneracion')[:50]
        return Response(NotificacionSerializer(qs, many=True).data)


class NotificacionMarcarLeidaView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        notif = get_object_or_404(Notificacion, pk=pk, idDestinatario=request.user)
        notif.leida = 1
        notif.fechaLectura = timezone.now()
        notif.save()
        return Response(NotificacionSerializer(notif).data)


class NotificacionMarcarTodasView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Notificacion.objects.filter(
            idDestinatario=request.user, leida=0
        ).update(leida=1, fechaLectura=timezone.now())
        return Response({'detail': 'Todas marcadas como leídas.'})
