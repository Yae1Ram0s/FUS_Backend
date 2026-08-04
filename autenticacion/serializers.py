from rest_framework import serializers
from django.contrib.auth.models import User
from .models import CorreoAutorizado


class LoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        # Único punto de todo el flujo de auth que no normalizaba el correo
        # (el resto de las vistas hace `.strip().lower()` a mano) — un correo
        # con mayúscula o espacio de más (típico de autocompletado en
        # celular) llegaba tal cual a la comparación exacta en LoginView.
        return value.strip().lower()


class UsuarioROL2Serializer(serializers.ModelSerializer):
    nombre = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = ['id', 'first_name', 'last_name', 'email', 'nombre']

    def get_nombre(self, obj):
        from solicitudes.utils import resolver_nombre
        return resolver_nombre(obj)
