from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import MedioRecepcion, PrioridadCriterio, Estatus
from .serializers import MedioRecepcionSerializer, PrioridadCriterioSerializer, EstatusSerializer


class MedioRecepcionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = MedioRecepcion.objects.filter(activo=1)
        para_turnado = request.query_params.get('paraTurnado')
        if para_turnado is not None:
            qs = qs.filter(paraTurnado=int(para_turnado))
        return Response(MedioRecepcionSerializer(qs, many=True).data)


class PrioridadCriterioListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs  = PrioridadCriterio.objects.filter(activo=1)
        nivel = request.query_params.get('nivel')
        if nivel:
            qs = qs.filter(nivel=nivel)
        return Response(PrioridadCriterioSerializer(qs, many=True).data)


class EstatusListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Estatus.objects.filter(activa=True)
        tipo_flujo = request.query_params.get('tipoFlujo')
        if tipo_flujo:
            # Devuelve los del tipo solicitado + los compartidos ('AMBOS')
            qs = qs.filter(tipoFlujo__in=[tipo_flujo, 'AMBOS'])
        return Response(EstatusSerializer(qs, many=True).data)
