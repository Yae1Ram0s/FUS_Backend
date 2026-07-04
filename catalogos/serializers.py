from rest_framework import serializers
from .models import MedioRecepcion, PrioridadCriterio, Estatus


class MedioRecepcionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = MedioRecepcion
        fields = ['id', 'nombreMedio', 'paraTurnado']


class PrioridadCriterioSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PrioridadCriterio
        fields = ['id', 'nivel', 'descripcionCriterio']


class EstatusSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Estatus
        fields = ['id', 'clave', 'nombre', 'tipoFlujo', 'orden', 'activa']
