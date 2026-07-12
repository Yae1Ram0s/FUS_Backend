from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from ..models import Notificacion
from ..serializers import NotificacionSerializer


class NotificacionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notificacion.objects.filter(
            idDestinatario=request.user
        ).order_by('-fechaGeneracion')

        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 50))))
        except (ValueError, TypeError):
            page, page_size = 1, 50

        total  = qs.count()
        offset = (page - 1) * page_size
        data   = NotificacionSerializer(qs[offset: offset + page_size], many=True).data
        return Response({'total': total, 'page': page, 'page_size': page_size, 'results': data})


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
