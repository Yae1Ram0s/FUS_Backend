from rest_framework.permissions import BasePermission

from autenticacion.models import CorreoAutorizado
from .utils import get_rol, _propietario_fus
from .models import Turnado


def _unidad_id(user):
    if not user:
        return None
    ca = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
    return ca.unidadAdministrativa_id if ca else None


def _es_rol1_o_turnado_destinatario(user, fus):
    """Rol 1 dueño de ESTE FUS (o su asistente EQUIPO_PARTICULAR), sin
    turnado de por medio, o Rol 2 que sea el destinatario específico de un
    Turnado activo de este FUS — nunca "cualquier Rol 1/Rol 2", siempre
    scoped al FUS puntual. Usado por: comisionar, atendido, y el gate de la
    reapertura automática Rechazado→En_seguimiento."""
    rol = get_rol(user)
    if rol in ('ROL1', 'EQUIPO_PARTICULAR'):
        return _propietario_fus(user) == fus.idSolicitanteInterno
    if rol == 'ROL2':
        return Turnado.objects.filter(idFus=fus, idDestinatario=user, activo=1).exists()
    return False


class EsRol1oRol2(BasePermission):
    """Rol 1 (Particular) o Rol 2 (Titular). Usado por: comisionados-disponibles
    (listado informativo, no una acción sobre un turnado específico)."""
    message = 'No autorizado.'

    def has_permission(self, request, view):
        return get_rol(request.user) in ('ROL1', 'ROL2')


class EsRol1oTurnadoDestinatario(BasePermission):
    """Rol 1 (o EQUIPO_PARTICULAR) dueño de este FUS, o Rol 2 destinatario
    específico del Turnado de este FUS. Usado por: comisionar, atendido."""
    message = 'No autorizado.'

    def has_permission(self, request, view):
        return get_rol(request.user) in ('ROL1', 'ROL2', 'EQUIPO_PARTICULAR')

    def has_object_permission(self, request, view, obj):
        return _es_rol1_o_turnado_destinatario(request.user, obj)


class EsRol1DuenoDelFUS(BasePermission):
    """Solo Rol 1 (Particular) dueño de ESTE FUS específico (quien lo
    registró, o su asistente EQUIPO_PARTICULAR) — no "cualquier Rol 1 de la
    dirección del comisionado": un FUS puede turnarse y comisionarse en una
    unidad distinta a la de quien lo registró (esa unidad puede no tener
    ningún Rol 1 propio, dejando la solicitud sin nadie que la valide).
    Usado por: concluir_asunto, rechazar_solicitud — la validación final
    queda exclusiva del dueño de la solicitud, el Titular (ROL2) ya no
    puede llamarlos."""
    message = 'No autorizado.'

    def has_permission(self, request, view):
        return get_rol(request.user) in ('ROL1', 'EQUIPO_PARTICULAR')

    def has_object_permission(self, request, view, obj):
        return _propietario_fus(request.user) == obj.idSolicitanteInterno


class EsComisionado(BasePermission):
    """Usuario con rol Comisionado. Usado por: mis-comisionados."""
    message = 'No autorizado.'

    def has_permission(self, request, view):
        return get_rol(request.user) == 'COMISIONADO'


class EsComisionadoAsignado(BasePermission):
    """El Comisionado autenticado, solo sobre el FUS que tiene asignado.
    Usado por: seguimiento (POST)."""
    message = 'No autorizado.'

    def has_permission(self, request, view):
        return get_rol(request.user) == 'COMISIONADO'

    def has_object_permission(self, request, view, obj):
        return obj.idComisionado_id == request.user.id


class PuedeVerSeguimientoComisionado(BasePermission):
    """GET seguimiento (historial): el Comisionado asignado, el Rol 1 dueño
    de este FUS (o su asistente EQUIPO_PARTICULAR), o el Rol 2 destinatario
    específico del Turnado — mismo criterio que comisionar/atendido, no
    "cualquier Rol 1/Rol 2 de la dirección del comisionado" (esa unidad
    puede no coincidir con la de quien registró o turnó el FUS)."""
    message = 'No autorizado.'

    def has_permission(self, request, view):
        return get_rol(request.user) in ('ROL1', 'ROL2', 'COMISIONADO', 'EQUIPO_PARTICULAR')

    def has_object_permission(self, request, view, obj):
        rol = get_rol(request.user)
        if rol == 'COMISIONADO':
            return obj.idComisionado_id == request.user.id
        return _es_rol1_o_turnado_destinatario(request.user, obj)
