from autenticacion.models import CorreoAutorizado
from .models import Bitacora


def get_rol(user):
    """Rol autorizado del usuario ('ROL1'/'ROL2') o '' si no está autorizado/activo."""
    autorizado = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
    return autorizado.rol if autorizado else ''


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
