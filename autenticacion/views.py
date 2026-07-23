import secrets
import string

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.utils import timezone
from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .models import CorreoAutorizado, CodigoOTP
from .serializers import LoginSerializer, UsuarioROL2Serializer
from .emails import enviar_correo_otp
from solicitudes.utils import get_rol, log_bitacora as _log
from catalogos.models import UnidadAdministrativa


def _set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        'refresh_token', str(refresh_token),
        httponly=True, secure=not settings.DEBUG, samesite='Lax',
        max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
    )
    return response


class LoginThrottle(AnonRateThrottle):
    scope = 'login'


class OTPThrottle(AnonRateThrottle):
    scope = 'otp'


def _generar_otp(email, ip):
    codigo = ''.join(secrets.choice(string.digits) for _ in range(6))
    CodigoOTP.objects.filter(email=email, usado=0).update(usado=1)
    CodigoOTP.objects.create(
        email=email,
        codigo=codigo,
        fechaExpiracion=timezone.now() + timedelta(minutes=15),
        ipSolicitante=ip,
    )
    return codigo


class VerificarCorreoView(APIView):
    """
    POST { email }
    Determina si el correo es nuevo (envía OTP) o existente (pide contraseña).
    """
    permission_classes  = [AllowAny]
    throttle_classes    = [OTPThrottle]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return Response({'detail': 'Correo requerido.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            autorizado = CorreoAutorizado.objects.get(email=email, activo=1)
        except CorreoAutorizado.DoesNotExist:
            return Response(
                {'detail': 'Correo no autorizado. Contacta al administrador.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if User.objects.filter(email=email).exists():
            return Response({'estado': 'existente'})

        # Usuario nuevo — generar y enviar OTP
        codigo = _generar_otp(email, request.META.get('REMOTE_ADDR'))
        enviar_correo_otp(
            email, codigo,
            intro='Recibimos una solicitud de acceso al Sistema de Control de Solicitudes. Utiliza el siguiente código para completar tu inicio de sesión.',
            asunto='Tu código de acceso — Sistema de Control de Solicitudes',
        )
        return Response({'estado': 'nuevo'})


class VerificarOTPView(APIView):
    """
    POST { email, codigo }
    """
    permission_classes = [AllowAny]
    throttle_classes   = [OTPThrottle]

    def post(self, request):
        email  = request.data.get('email', '').strip().lower()
        codigo = request.data.get('codigo', '').strip()

        try:
            CodigoOTP.objects.get(
                email=email,
                codigo=codigo,
                usado=0,
                fechaExpiracion__gt=timezone.now(),
            )
        except CodigoOTP.DoesNotExist:
            return Response(
                {'detail': 'Código incorrecto o expirado. Intenta de nuevo.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({'valido': True})


class EstablecerContrasenaView(APIView):
    """
    POST { email, codigo, password }
    Crea el usuario Django y devuelve tokens JWT.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email    = request.data.get('email', '').strip().lower()
        codigo   = request.data.get('codigo', '').strip()
        password = request.data.get('password', '')

        try:
            validate_password(password)
        except DjangoValidationError as e:
            return Response({'detail': ' '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            otp = CodigoOTP.objects.get(
                email=email,
                codigo=codigo,
                usado=0,
                fechaExpiracion__gt=timezone.now(),
            )
        except CodigoOTP.DoesNotExist:
            return Response(
                {'detail': 'Código inválido. Reinicia el proceso.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            autorizado = CorreoAutorizado.objects.select_related('unidadAdministrativa').get(email=email, activo=1)
        except CorreoAutorizado.DoesNotExist:
            return Response({'detail': 'Correo no autorizado.'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=autorizado.nombre,
            )
        except IntegrityError:
            return Response({'detail': 'Esta cuenta ya fue creada. Intenta iniciar sesión.'}, status=400)

        otp.usado = 1
        otp.save()

        refresh = RefreshToken.for_user(user)
        _log(usuario=email, rol=autorizado.rol, accion='REGISTRO', ip=request.META.get('REMOTE_ADDR'))

        response = Response({
            'access': str(refresh.access_token),
            'user': {
                'id':     user.id,
                'email':  email,
                'nombre': autorizado.nombre,
                'rol':    autorizado.rol,
                'unidadAdministrativa': autorizado.unidadAdministrativa.unidadAdministrativa if autorizado.unidadAdministrativa_id else None,
            },
        })
        return _set_refresh_cookie(response, refresh)


class ReenviarOTPView(APIView):
    """
    POST { email }
    Reenvía un nuevo OTP si el correo es válido y el usuario aún no existe.
    """
    permission_classes = [AllowAny]
    throttle_classes   = [OTPThrottle]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()

        try:
            autorizado = CorreoAutorizado.objects.get(email=email, activo=1)
        except CorreoAutorizado.DoesNotExist:
            return Response({'detail': 'Correo no autorizado.'}, status=status.HTTP_401_UNAUTHORIZED)

        if User.objects.filter(email=email).exists():
            return Response({'detail': 'Este usuario ya tiene cuenta activa.'}, status=status.HTTP_400_BAD_REQUEST)

        codigo = _generar_otp(email, request.META.get('REMOTE_ADDR'))
        enviar_correo_otp(
            email, codigo,
            intro='Solicitaste un nuevo código de acceso al Sistema de Control de Solicitudes. Utiliza el siguiente código para completar tu inicio de sesión.',
            asunto='Nuevo código de acceso — Sistema de Control de Solicitudes',
        )
        return Response({'enviado': True})


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = [LoginThrottle]

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        email    = ser.validated_data['email']
        password = ser.validated_data['password']
        ip       = request.META.get('REMOTE_ADDR')

        try:
            autorizado = CorreoAutorizado.objects.select_related('unidadAdministrativa').get(email=email, activo=1)
        except CorreoAutorizado.DoesNotExist:
            return Response({'detail': 'Correo no autorizado.'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            django_user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Correo autorizado (CorreoAutorizado) pero la persona nunca
            # completó la activación de su cuenta (verificar-correo → OTP →
            # establecer-contraseña), así que no existe su User todavía.
            # `code` le permite al frontend reencauzar automáticamente al
            # flujo de activación en vez de dejarlo varado en un mensaje.
            return Response(
                {
                    'detail': 'Tu cuenta aún no está activada. Te reenviamos un código a tu correo para crear tu contraseña.',
                    'code': 'cuenta_no_activada',
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = authenticate(request, username=django_user.username, password=password)
        if not user:
            return Response({'detail': 'Contraseña incorrecta.'}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(user)
        _log(usuario=email, rol=autorizado.rol, accion='INICIO_SESION', ip=ip)

        response = Response({
            'access': str(refresh.access_token),
            'user': {
                'id':     user.id,
                'email':  email,
                'nombre': autorizado.nombre or f"{user.first_name} {user.last_name}".strip(),
                'rol':    autorizado.rol,
                'unidadAdministrativa': autorizado.unidadAdministrativa.unidadAdministrativa if autorizado.unidadAdministrativa_id else None,
            }
        })
        return _set_refresh_cookie(response, refresh)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        email      = request.user.email
        ip         = request.META.get('REMOTE_ADDR')
        autorizado = CorreoAutorizado.objects.filter(email=email, activo=1).first()
        rol        = autorizado.rol if autorizado else ''
        _log(usuario=email, rol=rol, accion='CIERRE_SESION', ip=ip)
        response = Response({'detail': 'Sesión cerrada.'})
        response.delete_cookie('refresh_token')
        return response


class CookieTokenRefreshView(APIView):
    """Igual que TokenRefreshView de SimpleJWT, pero lee el refresh token de la
    cookie httpOnly en vez de esperarlo en el body."""
    permission_classes = [AllowAny]

    def post(self, request):
        raw_token = request.COOKIES.get('refresh_token')
        if not raw_token:
            return Response({'detail': 'No hay sesión activa.'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            refresh = RefreshToken(raw_token)
        except TokenError:
            return Response({'detail': 'Sesión expirada.'}, status=status.HTTP_401_UNAUTHORIZED)
        return Response({'access': str(refresh.access_token)})


class RecuperarContrasenaView(APIView):
    """
    POST { email }
    Envía OTP de recuperación a un usuario existente.
    """
    permission_classes = [AllowAny]
    throttle_classes   = [OTPThrottle]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return Response({'detail': 'Correo requerido.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            autorizado = CorreoAutorizado.objects.get(email=email, activo=1)
        except CorreoAutorizado.DoesNotExist:
            # No revelar si el correo existe o no
            return Response({'enviado': True})

        if not User.objects.filter(email=email).exists():
            return Response({'enviado': True})

        codigo = _generar_otp(email, request.META.get('REMOTE_ADDR'))
        enviar_correo_otp(
            email, codigo,
            intro='Recibimos una solicitud para restablecer tu contraseña del Sistema de Control de Solicitudes. Utiliza el siguiente código para continuar.',
            asunto='Recuperación de contraseña — Sistema de Control de Solicitudes',
        )
        return Response({'enviado': True})


class RestablecerContrasenaView(APIView):
    """
    POST { email, codigo, password }
    Restablece la contraseña de un usuario existente verificando el OTP.
    """
    permission_classes = [AllowAny]
    throttle_classes   = [OTPThrottle]

    def post(self, request):
        email    = request.data.get('email', '').strip().lower()
        codigo   = request.data.get('codigo', '').strip()
        password = request.data.get('password', '')

        try:
            validate_password(password)
        except DjangoValidationError as e:
            return Response({'detail': ' '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            otp = CodigoOTP.objects.get(
                email=email,
                codigo=codigo,
                usado=0,
                fechaExpiracion__gt=timezone.now(),
            )
        except CodigoOTP.DoesNotExist:
            return Response(
                {'detail': 'Código incorrecto o expirado.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'detail': 'Usuario no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        user.set_password(password)
        user.save()

        otp.usado = 1
        otp.save()

        autorizado = CorreoAutorizado.objects.filter(email=email, activo=1).first()
        _log(
            usuario=email,
            rol=autorizado.rol if autorizado else '',
            accion='RESTABLECER_CONTRASENA',
            ip=request.META.get('REMOTE_ADDR'),
        )

        return Response({'restablecida': True})


class UsuariosROL2View(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emails_rol2 = CorreoAutorizado.objects.filter(rol='ROL2', activo=1).values_list('email', flat=True)
        usuarios    = User.objects.filter(email__in=emails_rol2, is_active=True)
        ser         = UsuarioROL2Serializer(usuarios, many=True)
        return Response(ser.data)


# ── Panel Admin (ROL1) ────────────────────────────────────────────────────────

def _es_adm(user):
    return get_rol(user) == 'ROL1'


class CorreoAutorizadoListView(APIView):
    """GET / POST — lista y crea correos autorizados (solo ADM)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _es_adm(request.user):
            return Response({'detail': 'No autorizado.'}, status=403)

        qs = CorreoAutorizado.objects.select_related('unidadAdministrativa').all().order_by('rol', 'email')
        busqueda = request.query_params.get('search')
        rol      = request.query_params.get('rol')
        if busqueda: qs = qs.filter(email__icontains=busqueda) | qs.filter(nombre__icontains=busqueda)
        if rol:      qs = qs.filter(rol=rol)

        data = [{
            'id':     c.id,
            'email':  c.email,
            'nombre': c.nombre,
            'rol':    c.rol,
            'activo': c.activo,
            'tiene_cuenta': User.objects.filter(email=c.email).exists(),
            'unidadAdministrativa': c.unidadAdministrativa_id,
            'unidadAdministrativaNombre': c.unidadAdministrativa.unidadAdministrativa if c.unidadAdministrativa_id else None,
        } for c in qs]
        return Response(data)

    def post(self, request):
        if not _es_adm(request.user):
            return Response({'detail': 'No autorizado.'}, status=403)

        email  = request.data.get('email', '').strip().lower()
        nombre = request.data.get('nombre', '').strip()
        rol    = request.data.get('rol', 'ROL1')
        unidad_id = request.data.get('unidadAdministrativa') or None

        if not email or not nombre:
            return Response({'detail': 'Email y nombre son requeridos.'}, status=400)
        if rol not in ('ROL1', 'ROL2', 'COMISIONADO', 'EQUIPO_PARTICULAR'):
            return Response({'detail': 'Rol inválido.'}, status=400)
        if rol == 'COMISIONADO' and not unidad_id:
            return Response({'detail': 'Selecciona la dirección a la que quedará vinculado el comisionado.'}, status=400)
        if rol == 'EQUIPO_PARTICULAR':
            # La dirección no es libre: se hereda del ROL1 que da de alta al asistente.
            creador = CorreoAutorizado.objects.filter(email=request.user.email, activo=1).first()
            unidad_id = creador.unidadAdministrativa_id if creador else None
        if CorreoAutorizado.objects.filter(email=email).exists():
            return Response({'detail': 'Este correo ya está registrado.'}, status=400)
        if unidad_id and not UnidadAdministrativa.objects.filter(pk=unidad_id, activo=1).exists():
            return Response({'detail': 'Unidad administrativa inválida.'}, status=400)

        c = CorreoAutorizado.objects.create(
            email=email, nombre=nombre, rol=rol,
            unidadAdministrativa_id=unidad_id,
            idUsuarioRegistra=request.user.id,
        )
        return Response({
            'id': c.id, 'email': c.email, 'nombre': c.nombre, 'rol': c.rol, 'activo': c.activo,
            'unidadAdministrativa': c.unidadAdministrativa_id,
        }, status=201)


class CorreoAutorizadoDetailView(APIView):
    """PATCH — editar nombre, correo, rol, activo."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not _es_adm(request.user):
            return Response({'detail': 'No autorizado.'}, status=403)

        try:
            c = CorreoAutorizado.objects.get(pk=pk)
        except CorreoAutorizado.DoesNotExist:
            return Response({'detail': 'No encontrado.'}, status=404)

        if 'activo' in request.data:
            c.activo = int(request.data['activo'])
        if 'rol' in request.data and request.data['rol'] in ('ROL1', 'ROL2', 'COMISIONADO', 'EQUIPO_PARTICULAR'):
            c.rol = request.data['rol']
        if 'nombre' in request.data:
            c.nombre = request.data['nombre'].strip()
        if 'unidadAdministrativa' in request.data:
            unidad_id = request.data['unidadAdministrativa'] or None
            if unidad_id and not UnidadAdministrativa.objects.filter(pk=unidad_id, activo=1).exists():
                return Response({'detail': 'Unidad administrativa inválida.'}, status=400)
            c.unidadAdministrativa_id = unidad_id

        if 'email' in request.data:
            nuevo_email = request.data['email'].strip().lower()
            if nuevo_email != c.email:
                if CorreoAutorizado.objects.filter(email=nuevo_email).exclude(pk=pk).exists():
                    return Response({'detail': 'Ese correo ya está registrado.'}, status=400)
                # Actualizar Django User si ya tiene cuenta
                try:
                    django_user = User.objects.get(email=c.email)
                    django_user.email    = nuevo_email
                    django_user.username = nuevo_email
                    django_user.save()
                except User.DoesNotExist:
                    pass
                c.email = nuevo_email

        c.idUsuarioModifica = request.user.id
        c.save()

        return Response({
            'id': c.id, 'email': c.email, 'nombre': c.nombre, 'rol': c.rol, 'activo': c.activo,
            'unidadAdministrativa': c.unidadAdministrativa_id,
        })
