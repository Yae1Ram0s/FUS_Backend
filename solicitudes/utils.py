from autenticacion.models import CorreoAutorizado
from .models import Bitacora


def get_rol(user):
    """Rol autorizado del usuario ('ROL1'/'ROL2') o '' si no está autorizado/activo."""
    autorizado = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
    return autorizado.rol if autorizado else ''


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
