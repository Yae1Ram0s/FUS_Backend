from rest_framework import serializers
from .models import CorreoAutorizado


class UsuarioAdminPatchSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=255, required=False)
    rol = serializers.ChoiceField(choices=CorreoAutorizado.ROL_CHOICES, required=False)
    unidadAdministrativaId = serializers.IntegerField(required=False, allow_null=True)


class UsuarioAdminCrearSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    nombre = serializers.CharField(max_length=255)
    rol = serializers.ChoiceField(choices=tuple(choice for choice in CorreoAutorizado.ROL_CHOICES if choice[0] != 'ADMIN'))
    unidadAdministrativaId = serializers.IntegerField(required=False, allow_null=True)

    def validate_email(self, value):
        value = value.strip().lower()
        if not value.endswith('@anam.gob.mx'):
            raise serializers.ValidationError('Utiliza un correo institucional @anam.gob.mx.')
        return value


class RestablecerContrasenaSerializer(serializers.Serializer):
    metodo = serializers.ChoiceField(choices=('temporal', 'correo'))
