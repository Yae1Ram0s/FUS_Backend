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


def _equipo_particular_de(propietario):
    """Usuarios EQUIPO_PARTICULAR que asisten a este ROL1 — inverso de
    _propietario_fus: quienes tienen a `propietario` como
    CorreoAutorizado.idUsuarioRegistra. Comparten pantallas/visibilidad con
    él (ConsultarFUS), así que deben recibir las mismas notificaciones."""
    if not propietario:
        return User.objects.none()
    emails = CorreoAutorizado.objects.filter(
        rol='EQUIPO_PARTICULAR', activo=1, idUsuarioRegistra=propietario.id
    ).values_list('email', flat=True)
    return User.objects.filter(email__in=emails, is_active=True)


def es_marcador_atendido_o_concluido(texto):
    """True si `texto` es el marcador automático de auditoría que
    MarcarTurnadoAtendidoView/ConcluirPersonaTurnadoView crean en el modelo
    Seguimiento al marcar un turnado como Atendido/Concluido — no es una
    respuesta real de la persona turnada (a diferencia del de Rechazado, que
    sí se muestra, ya con el nombre de quien rechazó en vez de genérico). Se
    usa para ocultarlo del feed de "Respuestas y seguimiento" que ven Rol 1,
    Rol 2 y Equipo del Particular."""
    texto = texto or ''
    return texto.startswith('Atendido:') or texto == 'Concluido por el Particular.'


def resolver_nombre(user, mapa=None):
    """Nombre autoritativo del usuario (el mismo que ve en su sesión), con
    fallback. Con `mapa` (ver helpers.mapa_correos_autorizados) no golpea la
    BD — se usa así en listados para evitar una consulta por usuario."""
    if mapa is not None:
        entrada = mapa.get(user.email)
        if entrada:
            return entrada['nombre']
        return f"{user.first_name} {user.last_name}".strip() or user.email
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
