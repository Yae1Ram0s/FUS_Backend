from rest_framework import serializers
from django.contrib.auth.models import User
from .models import CorreoAutorizado


class LoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class UsuarioROL2Serializer(serializers.ModelSerializer):
    class Meta:
        model  = User
        fields = ['id', 'first_name', 'last_name', 'email']
