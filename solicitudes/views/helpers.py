from django.utils import timezone

from ..helpers import _resolver_unidad_administrativa
from ..utils import get_rol, log_bitacora, _propietario_fus

# _rol/_log se mantienen como alias locales para no tocar cada llamada existente.
_rol = get_rol
_log = log_bitacora


_ROL_FOLIO = {'ROL1': 'PARTICULAR', 'ROL2': 'TITULAR', 'EQUIPO_PARTICULAR': 'PARTICULAR'}

# EQUIPO_PARTICULAR (rol 4) opera como asistente de un ROL1 específico: mismas
# funciones sobre FUS/Calendario, pero limitado a los FUS del ROL1 que lo registró.
ROLES_PARTICULAR = ('ROL1', 'EQUIPO_PARTICULAR')

ROL1_ACCIONES = ['REGISTRO_RESPUESTA', 'CONCLUSION_FUS', 'ASIGNACION_ESTADO']
ROL2_ACCIONES = ['CONCLUSION_FUS', 'REGISTRO_RESPUESTA', 'REGISTRO_ACCION']
COMISIONADO_ACCIONES = ['ASIGNACION_COMISIONADO', 'SEGUIMIENTO_COMISIONADO', 'ATENCION_FUS', 'APROBACION_FUS', 'RECHAZO_FUS']


def _primer_error(ser):
    """Primer mensaje de error de un serializer inválido, como string plano
    (para responder {'detail': ...} igual que el resto de las vistas)."""
    for errores in ser.errors.values():
        if errores:
            return str(errores[0])
    return 'Datos inválidos.'


def _metadata_generacion():
    ahora = timezone.localtime(timezone.now())
    return f'Ciudad de México, {ahora.strftime("%d/%m/%Y")} a las {ahora.strftime("%H:%M")} h'
