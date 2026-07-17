from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from autenticacion.models import CorreoAutorizado
from ..models import FUS, Notificacion, SeguimientoRespuesta
from ..serializers import FUSSerializer, SeguimientoRespuestaSerializer
from ..helpers import notificar_por_correo
from .helpers import _rol, _log
from .turnado import _push_notificacion


def _unidad_id(user):
    if not user:
        return None
    ca = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
    return ca.unidadAdministrativa_id if ca else None


def _titulares_area(unidad_id):
    emails = CorreoAutorizado.objects.filter(
        rol='ROL2', activo=1, unidadAdministrativa_id=unidad_id
    ).values_list('email', flat=True)
    return User.objects.filter(email__in=emails, is_active=True)


class FUSComisionadosDisponiblesView(APIView):
    """GET — usuarios rol=COMISIONADO de la misma unidad administrativa que el Titular autenticado."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if _rol(request.user) != 'ROL2':
            return Response({'detail': 'No autorizado.'}, status=403)

        get_object_or_404(FUS, pk=pk, activo=1)

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
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        if _rol(user) != 'ROL2':
            return Response({'detail': 'No autorizado.'}, status=403)

        fus = get_object_or_404(FUS, pk=pk, activo=1)

        if fus.estatusParticular_id == 'Concluido':
            return Response(
                {'detail': 'La solicitud ya fue concluida y no puede asignarse a un comisionado.'}, status=400
            )
        if fus.estatusParticular_id != 'Turnado':
            return Response(
                {'detail': 'La solicitud debe estar en estatus "Turnado" para asignar un comisionado.'}, status=400
            )

        comisionado_id = request.data.get('comisionado_id')
        if not comisionado_id:
            return Response(
                {'detail': 'Debe seleccionar un comisionado para poder guardar la asignación.'}, status=400
            )

        comisionado = get_object_or_404(User, pk=comisionado_id)
        if _rol(comisionado) != 'COMISIONADO' or _unidad_id(comisionado) != _unidad_id(user):
            return Response(
                {'detail': 'El comisionado seleccionado no pertenece a tu dirección/unidad administrativa.'}, status=403
            )

        ip = request.META.get('REMOTE_ADDR')
        rol = _rol(user)
        est_ant = fus.estatusParticular_id

        fus.idComisionado = comisionado
        fus.fechaAsignacion = timezone.now()
        fus.estatusParticular_id = 'En_seguimiento'
        fus.idUsuarioModifica = user.id
        fus.save()

        _log(usuario=user.email, rol=rol, accion='ASIGNACION_COMISIONADO',
             ip=ip, folio=fus.folio, estado_ant=est_ant, estado_nuevo='En_seguimiento')

        titular_auth = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
        nombre_titular = titular_auth.nombre if titular_auth else (user.first_name or user.email)
        notif = Notificacion.objects.create(
            idDestinatario=comisionado,
            fusFolio=fus.folio,
            tipoEvento='ASIGNADO_COMISIONADO',
            mensaje=f"{nombre_titular} te asignó el FUS {fus.folio} para su seguimiento.",
        )
        _push_notificacion(notif)
        notificar_por_correo(notif)

        return Response(FUSSerializer(fus).data)


class MisFUSComisionadosView(APIView):
    """GET — FUS asignados al Comisionado autenticado (alimenta su Calendario)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if _rol(request.user) != 'COMISIONADO':
            return Response({'detail': 'No autorizado.'}, status=403)

        qs = FUS.objects.filter(idComisionado=request.user, activo=1).select_related(
            'idSolicitanteInterno', 'idMedioRecepcion', 'idComisionado'
        ).prefetch_related('evidencias').order_by('-fechaAsignacion')

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
        data   = FUSSerializer(qs[offset: offset + page_size], many=True).data
        return Response({'total': total, 'page': page, 'page_size': page_size, 'results': data})


class SeguimientoComisionadoListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        fus  = get_object_or_404(FUS, pk=pk, activo=1)
        user = request.user
        rol  = _rol(user)

        es_titular_area = rol == 'ROL2' and fus.idComisionado_id and _unidad_id(user) == _unidad_id(fus.idComisionado)
        es_comisionado_asignado = rol == 'COMISIONADO' and fus.idComisionado_id == user.id
        if not (es_titular_area or es_comisionado_asignado):
            return Response({'detail': 'No autorizado.'}, status=403)

        qs = SeguimientoRespuesta.objects.filter(idFus=fus, activo=1).select_related('idAutor').order_by('fechaRegistro')
        return Response(SeguimientoRespuestaSerializer(qs, many=True).data)

    def post(self, request, pk):
        fus  = get_object_or_404(FUS, pk=pk, activo=1)
        user = request.user

        if _rol(user) != 'COMISIONADO' or fus.idComisionado_id != user.id:
            return Response({'detail': 'No autorizado.'}, status=403)
        if fus.estatusParticular_id != 'En_seguimiento':
            return Response(
                {'detail': 'Solo se puede dar seguimiento mientras la solicitud está en seguimiento.'}, status=400
            )

        tipo = request.data.get('tipo')
        if tipo not in ('accion_por_emprender', 'avance'):
            return Response({'detail': 'Tipo de seguimiento inválido.'}, status=400)

        ser = SeguimientoRespuestaSerializer(data={'tipo': tipo, 'contenido': request.data.get('contenido')})
        ser.is_valid(raise_exception=True)

        seg = SeguimientoRespuesta.objects.create(idFus=fus, idAutor=user, **ser.validated_data)

        _log(usuario=user.email, rol=_rol(user), accion='SEGUIMIENTO_COMISIONADO',
             ip=request.META.get('REMOTE_ADDR'), folio=fus.folio)

        return Response(SeguimientoRespuestaSerializer(seg).data, status=201)


class FinalizarSeguimientoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        fus  = get_object_or_404(FUS, pk=pk, activo=1)

        if _rol(user) != 'COMISIONADO' or fus.idComisionado_id != user.id:
            return Response({'detail': 'No autorizado.'}, status=403)
        if fus.estatusParticular_id != 'En_seguimiento':
            return Response(
                {'detail': 'La solicitud debe estar en seguimiento para poder finalizarla.'}, status=400
            )

        ip      = request.META.get('REMOTE_ADDR')
        est_ant = fus.estatusParticular_id

        fus.estatusParticular_id = 'Pendiente_validacion'
        fus.idUsuarioModifica = user.id
        fus.save()

        SeguimientoRespuesta.objects.create(
            idFus=fus, idAutor=user, tipo='finalizacion',
            contenido=(request.data.get('contenido') or '').strip() or 'Seguimiento finalizado, pendiente de validación.',
        )

        _log(usuario=user.email, rol=_rol(user), accion='FINALIZACION_SEGUIMIENTO',
             ip=ip, folio=fus.folio, estado_ant=est_ant, estado_nuevo='Pendiente_validacion')

        for titular in _titulares_area(_unidad_id(user)):
            notif = Notificacion.objects.create(
                idDestinatario=titular,
                fusFolio=fus.folio,
                tipoEvento='SEGUIMIENTO_FINALIZADO',
                mensaje=f"El seguimiento del FUS {fus.folio} fue finalizado y está pendiente de tu validación.",
            )
            _push_notificacion(notif)
            notificar_por_correo(notif)

        return Response(FUSSerializer(fus).data)


class AprobarFUSView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        if _rol(user) != 'ROL2':
            return Response({'detail': 'No autorizado.'}, status=403)

        fus = get_object_or_404(FUS, pk=pk, activo=1)
        if fus.estatusParticular_id != 'Pendiente_validacion':
            return Response(
                {'detail': 'La solicitud debe estar pendiente de validación para poder aprobarla.'}, status=400
            )

        ip      = request.META.get('REMOTE_ADDR')
        est_ant = fus.estatusParticular_id

        fus.estatusParticular_id = 'Concluido'
        fus.fechaConclusion = timezone.now()
        fus.idUsuarioModifica = user.id
        fus.save()

        _log(usuario=user.email, rol=_rol(user), accion='APROBACION_FUS',
             ip=ip, folio=fus.folio, estado_ant=est_ant, estado_nuevo='Concluido')

        if fus.idComisionado:
            notif = Notificacion.objects.create(
                idDestinatario=fus.idComisionado,
                fusFolio=fus.folio,
                tipoEvento='SOLICITUD_APROBADA',
                mensaje=f"Tu seguimiento del FUS {fus.folio} fue aprobado y la solicitud fue concluida.",
            )
            _push_notificacion(notif)
            notificar_por_correo(notif)

        return Response(FUSSerializer(fus).data)


class RechazarFUSView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        if _rol(user) != 'ROL2':
            return Response({'detail': 'No autorizado.'}, status=403)

        fus = get_object_or_404(FUS, pk=pk, activo=1)
        if fus.estatusParticular_id != 'Pendiente_validacion':
            return Response(
                {'detail': 'La solicitud debe estar pendiente de validación para poder rechazarla.'}, status=400
            )

        motivo = (request.data.get('motivo') or '').strip()
        if not motivo:
            return Response({'detail': 'Debes escribir un motivo antes de rechazar.'}, status=400)

        ip      = request.META.get('REMOTE_ADDR')
        est_ant = fus.estatusParticular_id

        fus.estatusParticular_id = 'En_seguimiento'
        fus.idUsuarioModifica = user.id
        fus.save()

        SeguimientoRespuesta.objects.create(idFus=fus, idAutor=user, tipo='rechazo', contenido=motivo)

        _log(usuario=user.email, rol=_rol(user), accion='RECHAZO_FUS',
             ip=ip, folio=fus.folio, estado_ant=est_ant, estado_nuevo='En_seguimiento', obs=motivo)

        if fus.idComisionado:
            notif = Notificacion.objects.create(
                idDestinatario=fus.idComisionado,
                fusFolio=fus.folio,
                tipoEvento='SOLICITUD_RECHAZADA',
                mensaje=f"Tu seguimiento del FUS {fus.folio} fue rechazado: {motivo}. La solicitud regresó a tu bandeja.",
            )
            _push_notificacion(notif)
            notificar_por_correo(notif)

        return Response(FUSSerializer(fus).data)
