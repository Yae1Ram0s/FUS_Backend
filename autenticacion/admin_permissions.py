from rest_framework.permissions import BasePermission
from .models import CorreoAutorizado


class EsAdministradorSistema(BasePermission):
    message = 'Acceso exclusivo para administradores del sistema.'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and CorreoAutorizado.objects.filter(email=request.user.email, rol='ADMIN', activo=1).exists())
