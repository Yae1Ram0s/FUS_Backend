import hashlib

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

from .models import CorreoAutorizado
from .serializers import LoginSerializer, UsuarioROL2Serializer
from solicitudes.models import Bitacora


def _log(usuario, rol, accion, ip=None, folio=None, estado_ant=None, estado_nuevo=None, obs=None):
    Bitacora.objects.create(
        fusFolio=folio,
        usuario=usuario,
        rol=rol,
        accion=accion,
        estadoAnterior=estado_ant,
        estadoNuevo=estado_nuevo,
        ipCliente=ip,
        observaciones=obs,
    )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        email    = ser.validated_data['email']
        password = ser.validated_data['password']
        ip       = request.META.get('REMOTE_ADDR')

        # Verificar lista blanca
        try:
            autorizado = CorreoAutorizado.objects.get(email=email, activo=1)
        except CorreoAutorizado.DoesNotExist:
            return Response({'detail': 'Correo no autorizado.'}, status=status.HTTP_401_UNAUTHORIZED)

        # Autenticar — Django usa username; buscamos el User por email
        try:
            django_user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'detail': 'Usuario no registrado. Contacta al administrador.'}, status=status.HTTP_401_UNAUTHORIZED)

        user = authenticate(request, username=django_user.username, password=password)
        if not user:
            return Response({'detail': 'Contraseña incorrecta.'}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(user)

        _log(
            usuario=email,
            rol=autorizado.rol,
            accion='INICIO_SESION',
            ip=ip,
        )

        return Response({
            'access':  str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id':     user.id,
                'email':  email,
                'nombre': autorizado.nombre or f"{user.first_name} {user.last_name}".strip(),
                'rol':    autorizado.rol,
            }
        })


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        email      = request.user.email
        ip         = request.META.get('REMOTE_ADDR')
        autorizado = CorreoAutorizado.objects.filter(email=email, activo=1).first()
        rol        = autorizado.rol if autorizado else ''

        _log(usuario=email, rol=rol, accion='CIERRE_SESION', ip=ip)
        return Response({'detail': 'Sesión cerrada.'})


class UsuariosROL2View(APIView):
    """Devuelve la lista de usuarios con ROL2 para el modal de turnar."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emails_rol2 = CorreoAutorizado.objects.filter(rol='ROL2', activo=1).values_list('email', flat=True)
        usuarios    = User.objects.filter(email__in=emails_rol2, is_active=True)
        ser         = UsuarioROL2Serializer(usuarios, many=True)
        return Response(ser.data)
