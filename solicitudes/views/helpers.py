from django.contrib.auth.models import User
from django.utils import timezone

from autenticacion.models import CorreoAutorizado
from ..helpers import _resolver_unidad_administrativa
from ..utils import get_rol, log_bitacora

# _rol/_log se mantienen como alias locales para no tocar cada llamada existente.
_rol = get_rol
_log = log_bitacora


_ROL_FOLIO = {'ROL1': 'PARTICULAR', 'ROL2': 'TITULAR', 'EQUIPO_PARTICULAR': 'PARTICULAR'}

# EQUIPO_PARTICULAR (rol 4) opera como asistente de un ROL1 específico: mismas
# funciones sobre FUS/Calendario, pero limitado a los FUS del ROL1 que lo registró.
ROLES_PARTICULAR = ('ROL1', 'EQUIPO_PARTICULAR')

ROL1_ACCIONES = ['REGISTRO_RESPUESTA', 'CONCLUSION_FUS', 'ASIGNACION_ESTADO']
ROL2_ACCIONES = ['CONCLUSION_FUS', 'REGISTRO_RESPUESTA', 'REGISTRO_ACCION']
COMISIONADO_ACCIONES = ['ASIGNACION_COMISIONADO', 'SEGUIMIENTO_COMISIONADO', 'FINALIZACION_SEGUIMIENTO', 'APROBACION_FUS', 'RECHAZO_FUS']


def _propietario_fus(user):
    """Usuario ROL1 dueño de los FUS que `user` puede operar: él mismo si es
    ROL1, o el ROL1 que lo registró (CorreoAutorizado.idUsuarioRegistra) si es
    EQUIPO_PARTICULAR. None si no aplica o el creador ya no es válido."""
    rol = _rol(user)
    if rol == 'ROL1':
        return user
    if rol == 'EQUIPO_PARTICULAR':
        ca = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
        if ca and ca.idUsuarioRegistra:
            return User.objects.filter(pk=ca.idUsuarioRegistra, is_active=True).first()
    return None


def _metadata_generacion():
    ahora = timezone.localtime(timezone.now())
    return f'Ciudad de México, {ahora.strftime("%d/%m/%Y")} a las {ahora.strftime("%H:%M")} h'
