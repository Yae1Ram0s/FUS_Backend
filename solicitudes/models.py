import uuid

from django.db import models
from django.contrib.auth.models import User
from catalogos.models import MedioRecepcion


PRIORIDAD_CHOICES = [
    ('Alta', 'Alta'),
    ('Media', 'Media'),
    ('Baja', 'Baja'),
]


class FUS(models.Model):
    class Meta:
        db_table = 'scs_tbl_fus'

    ESTATUS_CHOICES = [
        ('Registrado', 'Registrado'),
        ('Turnado', 'Turnado'),
        ('Atendido', 'Atendido'),
        ('Concluido', 'Concluido'),
    ]

    folio = models.CharField(max_length=50, unique=True)
    idSolicitanteInterno = models.ForeignKey(
        User, null=True, on_delete=models.PROTECT, related_name='fus_registrados'
    )
    fechaHora = models.DateTimeField(null=True, blank=True)
    descripcion = models.TextField()
    contexto = models.TextField()
    idMedioRecepcion = models.ForeignKey(
        MedioRecepcion, null=True, on_delete=models.PROTECT
    )
    medioEspecificacion = models.CharField(max_length=255, null=True, blank=True)
    prioridad = models.CharField(max_length=10, choices=PRIORIDAD_CHOICES, null=True, blank=True)
    prioridadModificada = models.IntegerField(default=0)
    estatusParticular = models.CharField(max_length=20, choices=ESTATUS_CHOICES, default='Registrado')
    fechaConclusion = models.DateTimeField(null=True, blank=True)
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return self.folio


class SolicitanteExterno(models.Model):
    class Meta:
        db_table = 'scs_tbl_solicitantes_externos'

    idFus = models.OneToOneField(FUS, on_delete=models.CASCADE, related_name='solicitante_externo')
    nombre = models.CharField(max_length=255, null=True, blank=True)
    telefono = models.CharField(max_length=20, null=True, blank=True)
    correo = models.CharField(max_length=255, null=True, blank=True)
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return self.nombre or str(self.idFus)


class Evidencia(models.Model):
    """Archivos adjuntos del FUS. RN-09: PDF/JPG/PNG/DOCX, máx 10 MB por archivo, 30 MB por FUS."""

    class Meta:
        db_table = 'scs_tbl_evidencias'

    idFus = models.ForeignKey(FUS, on_delete=models.CASCADE, related_name='evidencias')
    nombreArchivo = models.CharField(max_length=255, null=True, blank=True)
    rutaArchivo = models.CharField(max_length=500, null=True, blank=True)
    tipoMime = models.CharField(max_length=100, null=True, blank=True)
    hashSha256 = models.CharField(max_length=64, null=True, blank=True)
    fechaCarga = models.DateTimeField(auto_now_add=True, null=True)
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return self.nombreArchivo or f"Evidencia {self.pk}"


class Turnado(models.Model):
    class Meta:
        db_table = 'scs_tbl_turnados'

    ESTATUS_CHOICES = [
        ('Recibido', 'Recibido'),
        ('En_seguimiento', 'En seguimiento'),
        ('Concluido', 'Concluido'),
    ]

    idFus = models.ForeignKey(FUS, on_delete=models.CASCADE, related_name='turnados')
    idRemitente = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, related_name='turnados_enviados'
    )
    idDestinatario = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, related_name='turnados_recibidos'
    )
    idMedio = models.ForeignKey(MedioRecepcion, on_delete=models.PROTECT, null=True)
    solicitudTexto = models.TextField(null=True, blank=True)
    fechaHoraTurnado = models.DateTimeField(null=True, blank=True)
    estatusTitular = models.CharField(max_length=20, choices=ESTATUS_CHOICES, default='Recibido')
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return f"Turnado {self.pk} – {self.idFus}"


class Seguimiento(models.Model):
    """Respuestas y actividades de seguimiento registradas por ROL2 (CU-06, RN-03)."""

    class Meta:
        db_table = 'scs_tbl_seguimientos'

    idTurnado = models.ForeignKey(Turnado, on_delete=models.CASCADE, related_name='seguimientos')
    fechaActividad = models.DateField(null=True, blank=True)
    descripcionActividad = models.TextField()
    accionTexto = models.CharField(max_length=500, null=True, blank=True)
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return f"Seguimiento {self.pk} – {self.idTurnado}"


class Accion(models.Model):
    """Acciones por emprender registradas por ROL2 (CU-07)."""

    class Meta:
        db_table = 'scs_tbl_acciones'

    idTurnado = models.ForeignKey(Turnado, on_delete=models.CASCADE, related_name='acciones')
    numeroOrden = models.IntegerField(null=True, blank=True)
    descripcion = models.TextField()
    completada = models.IntegerField(default=0)
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return f"Acción {self.numeroOrden} – {self.idTurnado}"


class Bitacora(models.Model):
    """Registro inmutable de auditoría. Solo lectura para todos los roles (RN-07, sección 6)."""

    class Meta:
        db_table = 'scs_tbl_bitacora'

    ACCION_CHOICES = [
        ('REGISTRO_FUS', 'Registro FUS'),
        ('TURNAR_FUS', 'Turnar FUS'),
        ('ASIGNACION_ESTADO', 'Asignación automática de estado'),
        ('REGISTRO_RESPUESTA', 'Registro de respuesta/seguimiento'),
        ('REGISTRO_ACCION', 'Registro de acción por emprender'),
        ('CONCLUSION_FUS', 'Conclusión FUS'),
        ('REAPERTURA_FUS', 'Reapertura FUS'),
        ('INICIO_SESION', 'Inicio de sesión'),
        ('CIERRE_SESION', 'Cierre de sesión'),
        ('ELIMINACION', 'Eliminación lógica'),
    ]

    fusFolio = models.CharField(max_length=100, null=True, blank=True)
    fechaHora = models.DateTimeField(auto_now_add=True)
    usuario = models.CharField(max_length=255)
    rol = models.CharField(max_length=50)
    accion = models.CharField(max_length=30, choices=ACCION_CHOICES)
    estadoAnterior = models.CharField(max_length=50, null=True, blank=True)
    estadoNuevo = models.CharField(max_length=50, null=True, blank=True)
    ipCliente = models.GenericIPAddressField(null=True, blank=True)
    observaciones = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.fechaHora} | {self.usuario} | {self.accion} | {self.fusFolio}"


class Notificacion(models.Model):
    """Notificaciones internas del sistema por evento de FUS (sección 5)."""

    class Meta:
        db_table = 'scs_tbl_notificaciones'

    TIPO_CHOICES = [
        ('TURNADO', 'FUS Turnado'),
        ('RESPUESTA', 'Nueva respuesta'),
        ('CAMBIO_ESTADO', 'Cambio de estado'),
        ('CONCLUIDO', 'FUS Concluido'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idDestinatario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notificaciones'
    )
    fusFolio = models.CharField(max_length=100)
    tipoEvento = models.CharField(max_length=20, choices=TIPO_CHOICES)
    mensaje = models.TextField()
    fechaGeneracion = models.DateTimeField(auto_now_add=True)
    leida = models.IntegerField(default=0)
    fechaLectura = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.tipoEvento} → {self.idDestinatario} | {self.fusFolio}"
