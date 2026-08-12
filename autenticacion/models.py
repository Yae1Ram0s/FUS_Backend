from django.db import models
from django.contrib.auth.models import User


class CorreoAutorizado(models.Model):
    """Lista blanca de correos @anam.gob.mx con acceso al sistema (RN-06, CU-01)."""

    class Meta:
        db_table = 'scs_auth_correos_autorizados'

    ROL_CHOICES = [
        ('ROL1', 'Particular del Titular'),
        ('ROL2', 'Titular / Enlace Estratégico'),
        ('COMISIONADO', 'Comisionado'),
        ('EQUIPO_PARTICULAR', 'Equipo del Particular'),
        ('ADMIN', 'Administrador del sistema'),
    ]

    email = models.EmailField(unique=True)
    nombre = models.CharField(max_length=255)
    rol = models.CharField(max_length=20, choices=ROL_CHOICES)
    unidadAdministrativa = models.ForeignKey(
        'catalogos.UnidadAdministrativa', null=True, blank=True,
        on_delete=models.SET_NULL, db_constraint=False,
        related_name='correos_autorizados',
        db_column='unidad_administrativa_id',
    )
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True, db_column='fecha_registro')
    fechaModificacion = models.DateTimeField(auto_now=True, null=True, db_column='fecha_modificacion')
    idUsuarioRegistra = models.IntegerField(null=True, blank=True, db_column='usuario_registra_id')
    idUsuarioModifica = models.IntegerField(null=True, blank=True, db_column='usuario_modifica_id')
    activo = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.email} ({self.rol})"


class CodigoOTP(models.Model):
    """OTP de verificación para primer acceso y recuperación de contraseña (CU-01, CU-02)."""

    class Meta:
        db_table = 'scs_auth_codigos_otp'
        indexes = [
            models.Index(fields=['-fechaGeneracion', 'estadoEnvio'], name='idx_otp_fecha_estado'),
        ]

    email = models.EmailField()
    codigo = models.CharField(max_length=10)
    fechaGeneracion = models.DateTimeField(auto_now_add=True, db_column='fecha_generacion')
    fechaExpiracion = models.DateTimeField(db_column='fecha_expiracion')
    usado = models.IntegerField(default=0)
    ipSolicitante = models.GenericIPAddressField(null=True, blank=True, db_column='ip_solicitante')
    intentosFallidos = models.PositiveSmallIntegerField(default=0, db_column='intentos_fallidos')
    estadoEnvio = models.CharField(
        max_length=20,
        choices=[
            ('SIN_CONFIRMACION', 'Sin confirmación'),
            ('ENVIADO', 'Enviado'),
            ('ERROR', 'Error'),
        ],
        default='SIN_CONFIRMACION',
        db_column='estado_envio',
    )
    fechaEnvio = models.DateTimeField(null=True, blank=True, db_column='fecha_envio')
    detalleEnvio = models.CharField(max_length=160, blank=True, default='', db_column='detalle_envio')

    def __str__(self):
        return f"OTP {self.email} – {'usado' if self.usado else 'vigente'}"


class SeguridadUsuario(models.Model):
    class Meta:
        db_table = 'scs_auth_seguridad_usuario'

    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='seguridad_scs', db_column='usuario_id')
    requiereCambioContrasena = models.BooleanField(default=False, db_column='requiere_cambio_contrasena')
    intentosFallidos = models.PositiveIntegerField(default=0, db_column='intentos_fallidos')
    bloqueadoHasta = models.DateTimeField(null=True, blank=True, db_column='bloqueado_hasta')
    versionSesion = models.PositiveIntegerField(default=0, db_column='version_sesion')
    ultimoIngreso = models.DateTimeField(null=True, blank=True, db_column='ultimo_ingreso')
    fechaModificacion = models.DateTimeField(auto_now=True, db_column='fecha_modificacion')


class AuditoriaAdministrativa(models.Model):
    class Meta:
        db_table = 'scs_auth_auditoria_administrativa'
        ordering = ['-fechaHora']
        indexes = [
            models.Index(fields=['fechaHora'], name='idx_admin_aud_fecha'),
            models.Index(fields=['actorEmail'], name='idx_admin_aud_actor'),
            models.Index(fields=['objetivoEmail'], name='idx_admin_aud_objetivo'),
        ]

    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+', db_column='actor_id')
    actorEmail = models.EmailField(db_column='actor_email')
    objetivo = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_column='objetivo_id')
    objetivoEmail = models.EmailField(blank=True, default='', db_column='objetivo_email')
    accion = models.CharField(max_length=60)
    detalle = models.JSONField(default=dict, blank=True)
    ipCliente = models.GenericIPAddressField(null=True, blank=True, db_column='ip_cliente')
    fechaHora = models.DateTimeField(auto_now_add=True, db_column='fecha_hora')


class HistorialSalud(models.Model):
    """Fotos periódicas de `_health()` (ver admin_views.py) para poder graficar
    disponibilidad/latencia en el tiempo — `_health()` en sí solo refleja el
    instante en que se consulta, nada se guardaba hasta ahora. Se llena vía
    `python manage.py registrar_salud_sistema`, agendado externamente igual
    que `revisar_sla` (ver ese comando)."""

    class Meta:
        db_table = 'scs_auth_historial_salud'
        ordering = ['-fechaHora']
        indexes = [models.Index(fields=['fechaHora'], name='idx_salud_fecha')]

    estado = models.CharField(max_length=20)
    detalle = models.JSONField(default=dict, blank=True)
    fechaHora = models.DateTimeField(auto_now_add=True, db_column='fecha_hora')
