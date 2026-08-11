from django.utils import timezone

from ..models import Turnado
from ..helpers import _resolver_unidad_administrativa
from ..utils import get_rol, log_bitacora, _propietario_fus

# _rol/_log se mantienen como alias locales para no tocar cada llamada existente.
_rol = get_rol
_log = log_bitacora


# EQUIPO_PARTICULAR (rol 4) opera como asistente de un ROL1 específico: mismas
# funciones sobre FUS/Calendario, pero limitado a los FUS del ROL1 que lo registró.
ROLES_PARTICULAR = ('ROL1', 'EQUIPO_PARTICULAR')

# 'ASIGNACION_ESTADO' y 'REAPERTURA_FUS' se generan como efecto colateral de
# la primera respuesta/reapertura de ROL2 y del Comisionado (ver
# SeguimientoListCreateView/MarcarTurnadoAtendidoView en turnado.py y
# SeguimientoComisionadoListCreateView en comisionado.py) — sin incluirlos
# aquí, ese propio usuario no podía encontrar esas acciones en su propia
# Bitácora/Búsqueda Avanzada, aunque él mismo las hubiera hecho.
ROL2_ACCIONES = ['CONCLUSION_FUS', 'REGISTRO_RESPUESTA', 'REGISTRO_ACCION', 'ASIGNACION_ESTADO', 'REAPERTURA_FUS']
COMISIONADO_ACCIONES = ['ASIGNACION_COMISIONADO', 'SEGUIMIENTO_COMISIONADO', 'ATENCION_FUS', 'APROBACION_FUS', 'RECHAZO_FUS', 'ASIGNACION_ESTADO', 'REAPERTURA_FUS']


def _puede_ver_fus(user, fus):
    """Política de acceso compartida por vistas de solo-lectura sensibles
    (descarga de evidencias, trazabilidad): ROL1 ve cualquier FUS,
    EQUIPO_PARTICULAR solo los de su ROL1 asociado, ROL2 solo si tiene un
    Turnado activo dirigido a él, COMISIONADO solo si el FUS le está
    asignado. Cualquier otro caso (rol distinto, o sin relación con el FUS)
    no tiene acceso — la vista que llame a esto debe responder 404."""
    rol = _rol(user)
    if rol == 'ROL1':
        return True
    if rol == 'EQUIPO_PARTICULAR':
        propietario = _propietario_fus(user)
        return bool(propietario) and fus.idSolicitanteInterno_id == propietario.id
    if rol == 'ROL2':
        return Turnado.objects.filter(idFus=fus, idDestinatario=user, activo=1).exists()
    if rol == 'COMISIONADO':
        return fus.idComisionado_id == user.id
    return False


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
