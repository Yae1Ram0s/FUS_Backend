from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from .models import SeguridadUsuario


class VersionedJWTAuthentication(JWTAuthentication):
    RUTAS_PERMITIDAS_CAMBIO_OBLIGATORIO = (
        '/auth/cambiar-contrasena-obligatoria/',
        '/auth/logout/',
    )

    def authenticate(self, request):
        resultado = super().authenticate(request)
        if resultado is None:
            return None
        user, validated_token = resultado
        security, _ = SeguridadUsuario.objects.get_or_create(usuario=user)
        ruta = request.path.rstrip('/') + '/'
        permitida = any(ruta.endswith(sufijo) for sufijo in self.RUTAS_PERMITIDAS_CAMBIO_OBLIGATORIO)
        if security.requiereCambioContrasena and not permitida:
            raise AuthenticationFailed(
                'Debes cambiar la contraseña temporal antes de continuar.',
                code='cambio_contrasena_requerido',
            )
        return user, validated_token

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        security, _ = SeguridadUsuario.objects.get_or_create(usuario=user)
        if int(validated_token.get('sessionVersion', 0)) != security.versionSesion:
            raise AuthenticationFailed('La sesión fue revocada.', code='sesion_revocada')
        return user
