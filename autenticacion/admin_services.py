import secrets
import string
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from .models import AuditoriaAdministrativa, SeguridadUsuario


def seguridad(user):
    return SeguridadUsuario.objects.get_or_create(usuario=user)[0]


def emitir_tokens(user):
    from rest_framework_simplejwt.tokens import RefreshToken
    refresh = RefreshToken.for_user(user)
    version = seguridad(user).versionSesion
    refresh['sessionVersion'] = version
    return refresh


def revocar_sesiones(user):
    estado = seguridad(user)
    estado.versionSesion += 1
    estado.save(update_fields=['versionSesion', 'fechaModificacion'])
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)
    return estado.versionSesion


def auditar(request, accion, objetivo=None, detalle=None):
    return AuditoriaAdministrativa.objects.create(
        actor=request.user, actorEmail=request.user.email,
        objetivo=objetivo, objetivoEmail=objetivo.email if objetivo else '',
        accion=accion, detalle=detalle or {}, ipCliente=request.META.get('REMOTE_ADDR'),
    )


def generar_temporal(longitud=16):
    alfabeto = string.ascii_letters + string.digits + '!@#$%&*'
    while True:
        value = ''.join(secrets.choice(alfabeto) for _ in range(longitud))
        if any(c.islower() for c in value) and any(c.isupper() for c in value) and any(c.isdigit() for c in value) and any(c in '!@#$%&*' for c in value):
            return value


@transaction.atomic
def restablecer_temporal(user, password=None):
    password = password or generar_temporal()
    user.set_password(password)
    user.is_active = True
    user.save(update_fields=['password', 'is_active'])
    estado = seguridad(user)
    estado.requiereCambioContrasena = True
    estado.bloqueadoHasta = None
    estado.intentosFallidos = 0
    estado.save(update_fields=['requiereCambioContrasena', 'bloqueadoHasta', 'intentosFallidos', 'fechaModificacion'])
    revocar_sesiones(user)
    return password


def usuario_payload(autorizado):
    user = User.objects.filter(email=autorizado.email).first()
    estado = seguridad(user) if user else None
    unidad = autorizado.unidadAdministrativa
    return {
        'id': user.id if user else None, 'autorizacionId': autorizado.id,
        'email': autorizado.email, 'nombre': autorizado.nombre, 'rol': autorizado.rol,
        # El catálogo usa `idUnidadAdministrativa` como PK de Django. Usar
        # `pk` mantiene este serializador desacoplado del nombre físico y evita
        # un AttributeError para todos los usuarios que sí tienen unidad.
        'unidadAdministrativa': ({'id': unidad.pk, 'nombre': unidad.unidadAdministrativa} if unidad else None),
        'activo': bool(autorizado.activo and (user is None or user.is_active)),
        'tieneContrasena': bool(user and user.has_usable_password()),
        'nuncaIngreso': not bool(estado and estado.ultimoIngreso),
        'bloqueado': bool(estado and estado.bloqueadoHasta and estado.bloqueadoHasta > timezone.now()),
        'requiereCambioContrasena': bool(estado and estado.requiereCambioContrasena),
        'ultimoIngreso': estado.ultimoIngreso.isoformat() if estado and estado.ultimoIngreso else None,
    }
