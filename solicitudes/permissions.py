from rest_framework.permissions import BasePermission

from autenticacion.models import CorreoAutorizado
from .utils import get_rol
from .models import Turnado


def _unidad_id(user):
    if not user:
        return None
    ca = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
    return ca.unidadAdministrativa_id if ca else None


def _es_rol1_o_turnado_destinatario(user, fus):
    """Rol 1 (dueño del FUS, sin turnado de por medio) o Rol 2 que sea el
    destinatario específico de un Turnado activo de este FUS — no "cualquier
    Rol 2 de la dirección". Usado por: comisionar, atendido, y el gate de la
    reapertura automática Rechazado→En_seguimiento."""
    rol = get_rol(user)
    if rol == 'ROL1':
        return True
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
    """Rol 1, o Rol 2 destinatario específico del Turnado de este FUS. Usado
    por: comisionar, atendido."""
    message = 'No autorizado.'

    def has_permission(self, request, view):
        return get_rol(request.user) in ('ROL1', 'ROL2')

    def has_object_permission(self, request, view, obj):
        return _es_rol1_o_turnado_destinatario(request.user, obj)


class EsRol1DeLaDireccionComisionado(BasePermission):
    """Solo Rol 1 (Particular), de la misma dirección/unidad del comisionado
    asignado al FUS. Usado por: concluir_asunto, rechazar_asunto — la
    validación final queda exclusiva del Particular, el Titular (ROL2) ya no
    puede llamarlos."""
    message = 'No autorizado.'

    def has_permission(self, request, view):
        return get_rol(request.user) == 'ROL1'

    def has_object_permission(self, request, view, obj):
        if not obj.idComisionado_id:
            return False
        return _unidad_id(request.user) == _unidad_id(obj.idComisionado)


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
    """GET seguimiento (historial): el Comisionado asignado, o Rol 1/Rol 2 de
    la misma dirección del comisionado asignado."""
    message = 'No autorizado.'

    def has_permission(self, request, view):
        return get_rol(request.user) in ('ROL1', 'ROL2', 'COMISIONADO')

    def has_object_permission(self, request, view, obj):
        rol = get_rol(request.user)
        if rol == 'COMISIONADO':
            return obj.idComisionado_id == request.user.id
        return bool(obj.idComisionado_id) and _unidad_id(request.user) == _unidad_id(obj.idComisionado)
