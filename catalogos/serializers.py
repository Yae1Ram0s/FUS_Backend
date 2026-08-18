from rest_framework import serializers
from .models import MedioRecepcion, Estatus, UnidadAdministrativa


class UnidadAdministrativaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = UnidadAdministrativa
        fields = ['idUnidadAdministrativa', 'clave', 'unidadAdministrativa', 'esUnidadAdministrativa', 'esUnidadDeNegocio']


class MedioRecepcionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = MedioRecepcion
        fields = ['id', 'nombreMedio', 'paraTurnado']


class EstatusSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Estatus
        fields = ['id', 'clave', 'nombre', 'tipoFlujo', 'orden', 'activa']
