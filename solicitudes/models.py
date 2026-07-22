import uuid

from django.db import models
from django.contrib.auth.models import User
from catalogos.models import MedioRecepcion, Estatus


PRIORIDAD_CHOICES = [
    ('Alta', 'Alta'),
    ('Media', 'Media'),
    ('Baja', 'Baja'),
]


class FUS(models.Model):
    class Meta:
        db_table = 'scs_tbl_fus'
        indexes = [
            # idx_fus_estatus: auto-created by FK constraint
            models.Index(fields=['folio'],             name='idx_fus_folio'),
            models.Index(fields=['fechaRegistro'],     name='idx_fus_fecha'),
            models.Index(fields=['idSolicitanteInterno'], name='idx_fus_solicitante'),
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
    criterios = models.TextField(null=True, blank=True)
    prioridadModificada = models.IntegerField(default=0)
    nombreExterno   = models.CharField(max_length=255, null=True, blank=True)
    telefonoExterno = models.CharField(max_length=20,  null=True, blank=True)
    correoExterno   = models.CharField(max_length=255, null=True, blank=True)
    estatusParticular = models.ForeignKey(
        Estatus,
        on_delete=models.PROTECT,
        to_field='clave',
        db_column='estatusParticular',
        related_name='fus_set',
        default='Registrado',
    )
    fechaConclusion = models.DateTimeField(null=True, blank=True)
    fechaLimite = models.DateTimeField(null=True, blank=True)
    idComisionado = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT, related_name='fus_comisionados'
    )
    fechaAsignacion = models.DateTimeField(null=True, blank=True)
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return self.folio



class Evidencia(models.Model):
    """Archivos adjuntos del FUS. RN-09: PDF/JPG/PNG/DOCX, máx 10 MB por archivo, 30 MB por FUS."""

    class Meta:
        db_table = 'scs_tbl_evidencias'

    idFus = models.ForeignKey(FUS, on_delete=models.CASCADE, related_name='evidencias')
    nombreArchivo = models.CharField(max_length=255, null=True, blank=True)
    rutaArchivo = models.CharField(max_length=500, null=True, blank=True)
    tipoMime = models.CharField(max_length=100, null=True, blank=True)
    hashSha256 = models.CharField(max_length=64, null=True, blank=True)
    comentarios = models.TextField(null=True, blank=True)
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
        indexes = [
            models.Index(fields=['idDestinatario'], name='idx_turnado_dest'),
            # idx_turnado_estatus: auto-created by FK constraint
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
    estatusTitular = models.ForeignKey(
        Estatus,
        on_delete=models.PROTECT,
        to_field='clave',
        db_column='estatusTitular',
        related_name='turnados_set',
        default='Recibido',
    )
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
        db_table = 'scs_tbl_respuestas'
        ordering = ['fechaRegistro']

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


class Bitacora(models.Model):
    """Registro inmutable de auditoría. Solo lectura para todos los roles (RN-07, sección 6)."""

    class Meta:
        db_table = 'scs_tbl_bitacora'
        indexes = [
            models.Index(fields=['usuario'],   name='idx_bitacora_usuario'),
            models.Index(fields=['fusFolio'],  name='idx_bitacora_folio'),
            models.Index(fields=['fechaHora'], name='idx_bitacora_fecha'),
        ]

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
        ('RESTABLECER_CONTRASENA', 'Restablecimiento de contraseña'),
        ('ELIMINACION', 'Eliminación lógica'),
        ('ASIGNACION_COMISIONADO', 'Asignación a comisionado'),
        ('SEGUIMIENTO_COMISIONADO', 'Seguimiento de comisionado'),
        ('FINALIZACION_SEGUIMIENTO', 'Finalización de seguimiento'),  # ya no se genera; se conserva por bitácora histórica
        ('ATENCION_FUS', 'Atención de FUS (comisionado)'),
        ('APROBACION_FUS', 'Aprobación de FUS'),
        ('RECHAZO_FUS', 'Rechazo de FUS'),
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
        ('SLA_POR_VENCER', 'SLA por vencer'),
        ('ACTIVIDAD', 'Actividad de calendario'),
        ('ASIGNADO_COMISIONADO', 'FUS asignado a comisionado'),
        ('SEGUIMIENTO_FINALIZADO', 'Seguimiento finalizado'),
        ('SOLICITUD_APROBADA', 'Solicitud aprobada'),
        ('SOLICITUD_RECHAZADA', 'Solicitud rechazada'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idDestinatario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notificaciones'
    )
    fusFolio = models.CharField(max_length=100)
    tipoEvento = models.CharField(max_length=25, choices=TIPO_CHOICES)
    mensaje = models.TextField()
    fechaGeneracion = models.DateTimeField(auto_now_add=True)
    leida = models.IntegerField(default=0)
    fechaLectura = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.tipoEvento} → {self.idDestinatario} | {self.fusFolio}"


class Actividad(models.Model):
    """Eventos del calendario (reuniones, límites, actividad institucional)."""

    class Meta:
        db_table = 'scs_tbl_actividades'

    TIPO_CHOICES = [
        ('reunion', 'Reunión'),
        ('fus', 'FUS vinculado'),
        ('limite', 'Fecha límite'),
        ('institucional', 'Institucional'),
    ]

    titulo = models.CharField(max_length=200)
    fecha = models.DateField()
    horaInicio = models.TimeField()
    horaFin = models.TimeField()
    descripcion = models.TextField(blank=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='reunion')
    idCreador = models.ForeignKey(User, on_delete=models.CASCADE, related_name='actividades_creadas')
    idFusRelacionado = models.ForeignKey(FUS, on_delete=models.SET_NULL, null=True, blank=True)
    participantes = models.ManyToManyField(User, related_name='actividades_invitado', blank=True)
    fechaCreacion = models.DateTimeField(auto_now_add=True)
    activo = models.SmallIntegerField(default=1)

    def __str__(self):
        return f"{self.titulo} — {self.fecha}"


class SeguimientoRespuesta(models.Model):
    """Bitácora de seguimiento del Comisionado sobre un FUS (acciones, avances,
    finalización y rechazos) — feed cronológico independiente del Seguimiento
    de ROL2 sobre Turnado."""

    class Meta:
        db_table = 'scs_tbl_seguimiento_comisionado'
        ordering = ['fechaRegistro']

    TIPO_CHOICES = [
        ('accion_por_emprender', 'Acción por emprender'),
        ('avance', 'Avance'),
        ('finalizacion', 'Finalización'),
        ('rechazo', 'Rechazo'),
    ]

    idFus = models.ForeignKey(FUS, on_delete=models.CASCADE, related_name='seguimientosComisionado')
    idAutor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='seguimientos_comisionado')
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
    contenido = models.TextField()
    fechaRegistro = models.DateTimeField(auto_now_add=True)
    activo = models.SmallIntegerField(default=1)

    def __str__(self):
        return f"{self.idFus.folio} — {self.tipo}"
