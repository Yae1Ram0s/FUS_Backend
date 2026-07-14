from django.db.models import Q
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from ..models import Actividad, Notificacion
from ..serializers import ActividadSerializer
from ..helpers import notificar_por_correo
from .turnado import _push_notificacion


class ActividadListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mes = request.query_params.get('mes')  # 'YYYY-MM'
        qs = Actividad.objects.filter(
            Q(idCreador=request.user) | Q(participantes=request.user), activo=1
        ).distinct().select_related('idFusRelacionado').prefetch_related('participantes')
        if mes:
            qs = qs.filter(fecha__year=int(mes[:4]), fecha__month=int(mes[5:7]))
        return Response(ActividadSerializer(qs, many=True).data)

    def post(self, request):
        data = request.data
        forzar = data.get('forzarConflicto', False)
        if not forzar:
            conflicto = Actividad.objects.filter(
                idCreador=request.user, fecha=data['fecha'], activo=1,
                horaInicio__lt=data['horaFin'], horaFin__gt=data['horaInicio'],
            ).exists()
            if conflicto:
                return Response({'conflicto': True, 'detail': 'Ya existe otra actividad en ese horario.'}, status=409)
        actividad = Actividad.objects.create(
            titulo=data['titulo'], fecha=data['fecha'], horaInicio=data['horaInicio'], horaFin=data['horaFin'],
            descripcion=data.get('descripcion', ''), tipo=data.get('tipo', 'reunion'),
            idCreador=request.user,
            idFusRelacionado_id=data.get('idFusRelacionado') or None,
        )
        participantes_ids = data.get('participantes', [])
        if participantes_ids:
            actividad.participantes.set(participantes_ids)
            for uid in participantes_ids:
                notif = Notificacion.objects.create(
                    idDestinatario_id=uid, fusFolio=actividad.idFusRelacionado.folio if actividad.idFusRelacionado else '',
                    tipoEvento='ACTIVIDAD', mensaje=f"Fuiste invitado a '{actividad.titulo}' el {actividad.fecha}.",
                )
                _push_notificacion(notif)
                notificar_por_correo(notif)
        return Response(ActividadSerializer(actividad).data, status=201)


class ActividadDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        actividad = get_object_or_404(Actividad, pk=pk, idCreador=request.user, activo=1)
        for campo in ['titulo', 'fecha', 'horaInicio', 'horaFin', 'descripcion', 'tipo']:
            if campo in request.data:
                setattr(actividad, campo, request.data[campo])
        actividad.save()
        if 'participantes' in request.data:
            actividad.participantes.set(request.data['participantes'])
        return Response(ActividadSerializer(actividad).data)

    def delete(self, request, pk):
        actividad = get_object_or_404(Actividad, pk=pk, idCreador=request.user, activo=1)
        actividad.activo = 0
        actividad.save()
        return Response(status=204)
