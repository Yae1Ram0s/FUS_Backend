from django.db.models import Q
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from ..models import Actividad, FUS, Notificacion
from ..serializers import ActividadSerializer
from ..services import notificar_por_correo, push_notificacion
from .helpers import _puede_ver_fus


class ActividadListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mes = request.query_params.get('mes')  # 'YYYY-MM'
        qs = Actividad.objects.filter(
            Q(idCreador=request.user) | Q(participantes=request.user), activo=1
        ).exclude(
            # El recordatorio automático de "Vence FUS" (tipo='limite', creado
            # al registrar/turnar con fechaLimite) deja de ser relevante una
            # vez que el FUS ya se concluyó — mismo criterio que
            # FUSSerializer.get_estadoTemporalidad. No afecta actividades que
            # el usuario haya agendado él mismo.
            tipo='limite', idFusRelacionado__estatusParticular_id='Concluido',
        ).distinct().select_related('idFusRelacionado').prefetch_related('participantes')
        if mes:
            qs = qs.filter(fecha__year=int(mes[:4]), fecha__month=int(mes[5:7]))
        return Response(ActividadSerializer(qs, many=True).data)

    def post(self, request):
        data = request.data
        fus_id = data.get('idFusRelacionado') or None
        if fus_id:
            # Sin esto, cualquier usuario autenticado podía vincular una
            # actividad a un FUS ajeno con solo mandar su id, y luego leer
            # `fusFolio` en la respuesta de su propio GET — un oráculo para
            # enumerar folios de FUS a los que no tiene acceso.
            fus = get_object_or_404(FUS, pk=fus_id, activo=1)
            if not _puede_ver_fus(request.user, fus):
                return Response({'detail': 'No autorizado.'}, status=403)

        participantes_ids = data.get('participantes', [])
        forzar = data.get('forzarConflicto', False)
        if not forzar:
            # También cuenta como conflicto si algún invitado ya tiene otra
            # actividad en ese horario, no solo el creador — antes solo se
            # comprobaba "¿yo ya tengo algo ahí?".
            conflicto = Actividad.objects.filter(
                Q(idCreador=request.user) | Q(participantes__in=participantes_ids),
                fecha=data['fecha'], activo=1,
                horaInicio__lt=data['horaFin'], horaFin__gt=data['horaInicio'],
            ).exists()
            if conflicto:
                return Response({'conflicto': True, 'detail': 'Ya existe otra actividad en ese horario.'}, status=409)
        actividad = Actividad.objects.create(
            titulo=data['titulo'], fecha=data['fecha'], horaInicio=data['horaInicio'], horaFin=data['horaFin'],
            descripcion=data.get('descripcion', ''), tipo=data.get('tipo', 'reunion'),
            idCreador=request.user,
            idFusRelacionado_id=fus_id,
        )
        if participantes_ids:
            actividad.participantes.set(participantes_ids)
            for uid in participantes_ids:
                notif = Notificacion.objects.create(
                    idDestinatario_id=uid, fusFolio=actividad.idFusRelacionado.folio if actividad.idFusRelacionado else '',
                    tipoEvento='ACTIVIDAD', mensaje=f"Fuiste invitado a '{actividad.titulo}' el {actividad.fecha}.",
                )
                push_notificacion(notif)
                notificar_por_correo(notif)
        return Response(ActividadSerializer(actividad).data, status=201)


class ActividadDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        actividad = get_object_or_404(Actividad, pk=pk, idCreador=request.user, activo=1)
        data = request.data

        participantes_nuevos = data.get('participantes')
        cambia_horario = any(campo in data for campo in ('fecha', 'horaInicio', 'horaFin'))
        if cambia_horario and not data.get('forzarConflicto', False):
            # Mismo chequeo que al crear (ver POST): si no se repite aquí, se
            # puede mover una actividad a un horario ya ocupado —propio o de
            # un invitado— sin ningún aviso de conflicto.
            fecha      = data.get('fecha', actividad.fecha)
            horaInicio = data.get('horaInicio', actividad.horaInicio)
            horaFin    = data.get('horaFin', actividad.horaFin)
            participantes_ids = (
                participantes_nuevos if participantes_nuevos is not None
                else list(actividad.participantes.values_list('id', flat=True))
            )
            conflicto = Actividad.objects.filter(
                Q(idCreador=request.user) | Q(participantes__in=participantes_ids),
                fecha=fecha, activo=1,
                horaInicio__lt=horaFin, horaFin__gt=horaInicio,
            ).exclude(pk=actividad.pk).exists()
            if conflicto:
                return Response({'conflicto': True, 'detail': 'Ya existe otra actividad en ese horario.'}, status=409)

        for campo in ['titulo', 'fecha', 'horaInicio', 'horaFin', 'descripcion', 'tipo']:
            if campo in data:
                setattr(actividad, campo, data[campo])
        actividad.save()

        if participantes_nuevos is not None:
            # Antes solo se notificaba a los participantes al CREAR la
            # actividad: alguien agregado en una edición nunca se enteraba.
            anteriores = set(actividad.participantes.values_list('id', flat=True))
            actividad.participantes.set(participantes_nuevos)
            agregados = {int(uid) for uid in participantes_nuevos} - anteriores
            for uid in agregados:
                notif = Notificacion.objects.create(
                    idDestinatario_id=uid,
                    fusFolio=actividad.idFusRelacionado.folio if actividad.idFusRelacionado else '',
                    tipoEvento='ACTIVIDAD', mensaje=f"Fuiste invitado a '{actividad.titulo}' el {actividad.fecha}.",
                )
                push_notificacion(notif)
                notificar_por_correo(notif)

        return Response(ActividadSerializer(actividad).data)

    def delete(self, request, pk):
        actividad = get_object_or_404(Actividad, pk=pk, idCreador=request.user, activo=1)
        actividad.activo = 0
        actividad.save()
        return Response(status=204)
