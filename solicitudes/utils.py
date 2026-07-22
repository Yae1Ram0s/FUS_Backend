from django.contrib.auth.models import User

from autenticacion.models import CorreoAutorizado
from .models import Bitacora


def get_rol(user):
    """Rol autorizado del usuario ('ROL1'/'ROL2') o '' si no está autorizado/activo."""
    autorizado = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
    return autorizado.rol if autorizado else ''


def _propietario_fus(user):
    """Usuario ROL1 dueño de los FUS que `user` puede operar: él mismo si es
    ROL1, o el ROL1 que lo registró (CorreoAutorizado.idUsuarioRegistra) si es
    EQUIPO_PARTICULAR. None si no aplica o el creador ya no es válido.

    Vive aquí (módulo hoja, sin dependencias hacia arriba) y no en
    views/helpers.py porque solicitudes.permissions también la necesita —
    importarla desde views/ crea un ciclo (views/__init__ -> serializers ->
    permissions)."""
    rol = get_rol(user)
    if rol == 'ROL1':
        return user
    if rol == 'EQUIPO_PARTICULAR':
        ca = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
        if ca and ca.idUsuarioRegistra:
            return User.objects.filter(pk=ca.idUsuarioRegistra, is_active=True).first()
    return None


def resolver_nombre(user):
    """Nombre autoritativo del usuario (el mismo que ve en su sesión), con fallback."""
    autorizado = CorreoAutorizado.objects.filter(email=user.email).first()
    if autorizado:
        return autorizado.nombre
    return f"{user.first_name} {user.last_name}".strip() or user.email


def log_bitacora(usuario, rol, accion, ip=None, folio=None, estado_ant=None, estado_nuevo=None, obs=None):
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
