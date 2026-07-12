from django.utils import timezone

from ..helpers import _resolver_unidad_administrativa
from ..utils import get_rol, log_bitacora

# _rol/_log se mantienen como alias locales para no tocar cada llamada existente.
_rol = get_rol
_log = log_bitacora


_ROL_FOLIO = {'ROL1': 'PARTICULAR', 'ROL2': 'TITULAR'}

ROL1_ACCIONES = ['REGISTRO_RESPUESTA', 'CONCLUSION_FUS', 'ASIGNACION_ESTADO']
ROL2_ACCIONES = ['CONCLUSION_FUS', 'REGISTRO_RESPUESTA', 'REGISTRO_ACCION']


def _metadata_generacion():
    ahora = timezone.localtime(timezone.now())
    return f'Ciudad de México, {ahora.strftime("%d/%m/%Y")} a las {ahora.strftime("%H:%M")} h'
