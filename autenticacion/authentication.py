from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from .models import SeguridadUsuario


class VersionedJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        security, _ = SeguridadUsuario.objects.get_or_create(usuario=user)
        if int(validated_token.get('sessionVersion', 0)) != security.versionSesion:
            raise AuthenticationFailed('La sesión fue revocada.', code='sesion_revocada')
        return user
