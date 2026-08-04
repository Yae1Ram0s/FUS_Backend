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
            models.Index(fields=['fechaLimite'],       name='idx_fus_limite'),
            models.Index(fields=['fechaConclusion'],   name='idx_fus_conclusion'),
            models.Index(fields=['prioridad'],         name='idx_fus_prioridad'),
            models.Index(fields=['idComisionado'],     name='idx_fus_comisionado'),
            models.Index(fields=['activo', 'fechaRegistro'], name='idx_fus_act_fecha'),
        ]

    folio = models.CharField(max_length=50, unique=True)
    idSolicitanteInterno = models.ForeignKey(
        User, null=True, on_delete=models.PROTECT, related_name='fus_registrados',
        db_column='solicitante_interno_id',
    )
    fechaHora = models.DateTimeField(null=True, blank=True, db_column='fecha_hora')
    descripcion = models.TextField()
    contexto = models.TextField()
    idMedioRecepcion = models.ForeignKey(
        MedioRecepcion, null=True, on_delete=models.PROTECT,
        db_column='medio_recepcion_id',
    )
    medioEspecificacion = models.CharField(
        max_length=255, null=True, blank=True,
        db_column='medio_especificacion',
    )
    prioridad = models.CharField(max_length=10, choices=PRIORIDAD_CHOICES, null=True, blank=True)
    criterios = models.TextField(null=True, blank=True)
    prioridadModificada = models.IntegerField(
        default=0, db_column='prioridad_modificada',
    )
    nombreExterno = models.CharField(
        max_length=255, null=True, blank=True,
        db_column='solicitante_externo_nombre',
    )
    telefonoExterno = models.CharField(
        max_length=20, null=True, blank=True,
        db_column='solicitante_externo_telefono',
    )
    correoExterno = models.CharField(
        max_length=255, null=True, blank=True,
        db_column='solicitante_externo_correo',
    )
    estatusParticular = models.ForeignKey(
        Estatus,
        on_delete=models.PROTECT,
        to_field='clave',
        db_column='estatus_particular',
        related_name='fus_set',
        default='Registrado',
    )
    fechaConclusion = models.DateTimeField(
        null=True, blank=True, db_column='fecha_conclusion',
    )
    fechaLimite = models.DateTimeField(
        null=True, blank=True, db_column='fecha_limite',
    )
    idComisionado = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT,
        related_name='fus_comisionados', db_column='comisionado_id',
    )
    fechaAsignacion = models.DateTimeField(
        null=True, blank=True, db_column='fecha_asignacion',
    )
    fechaRegistro = models.DateTimeField(
        auto_now_add=True, null=True, db_column='fecha_registro',
    )
    fechaModificacion = models.DateTimeField(
        auto_now=True, null=True, db_column='fecha_modificacion',
    )
    idUsuarioRegistra = models.IntegerField(
        null=True, blank=True, db_column='usuario_registra_id',
    )
    idUsuarioModifica = models.IntegerField(
        null=True, blank=True, db_column='usuario_modifica_id',
    )
    activo = models.IntegerField(default=1)

    def __str__(self):
        return self.folio



class Evidencia(models.Model):
    """Archivos adjuntos del FUS. RN-09: PDF/JPG/PNG/DOCX, máx 10 MB por archivo, 30 MB por FUS."""

    class Meta:
        db_table = 'scs_tbl_evidencias'

    idFus = models.ForeignKey(
        FUS, on_delete=models.CASCADE, related_name='evidencias',
        db_column='fus_id',
    )
    nombreArchivo = models.CharField(
        max_length=255, null=True, blank=True, db_column='nombre_archivo',
    )
    rutaArchivo = models.CharField(
        max_length=500, null=True, blank=True, db_column='ruta_archivo',
    )
    tipoMime = models.CharField(
        max_length=100, null=True, blank=True, db_column='tipo_mime',
    )
    hashSha256 = models.CharField(
        max_length=64, null=True, blank=True, db_column='hash_sha256',
    )
    tamanoBytes = models.PositiveIntegerField(
        null=True, blank=True, db_column='tamano_bytes',
    )
    comentarios = models.TextField(null=True, blank=True)
    fechaCarga = models.DateTimeField(
        auto_now_add=True, null=True, db_column='fecha_carga',
    )
    fechaRegistro = models.DateTimeField(
        auto_now_add=True, null=True, db_column='fecha_registro',
    )
    fechaModificacion = models.DateTimeField(
        auto_now=True, null=True, db_column='fecha_modificacion',
    )
    idUsuarioRegistra = models.IntegerField(
        null=True, blank=True, db_column='usuario_registra_id',
    )
    idUsuarioModifica = models.IntegerField(
        null=True, blank=True, db_column='usuario_modifica_id',
    )
    activo = models.IntegerField(default=1)

    def __str__(self):
        return self.nombreArchivo or f"Evidencia {self.pk}"


class Turnado(models.Model):
    class Meta:
        db_table = 'scs_tbl_turnados'
        indexes = [
            models.Index(fields=['idDestinatario'], name='idx_turnado_dest'),
            models.Index(fields=['fechaHoraTurnado'], name='idx_turnado_fecha'),
            # idx_turnado_estatus: auto-created by FK constraint
        ]

    idFus = models.ForeignKey(
        FUS, on_delete=models.CASCADE, related_name='turnados',
        db_column='fus_id',
    )
    idRemitente = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True,
        related_name='turnados_enviados', db_column='remitente_id',
    )
    idDestinatario = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True,
        related_name='turnados_recibidos', db_column='destinatario_id',
    )
    idMedio = models.ForeignKey(
        MedioRecepcion, on_delete=models.PROTECT, null=True,
        db_column='medio_recepcion_id',
    )
    solicitudTexto = models.TextField(
        null=True, blank=True, db_column='solicitud_texto',
    )
    fechaHoraTurnado = models.DateTimeField(
        null=True, blank=True, db_column='fecha_hora_turnado',
    )
    estatusTitular = models.ForeignKey(
        Estatus,
        on_delete=models.PROTECT,
        to_field='clave',
        db_column='estatus_titular',
        related_name='turnados_set',
        default='Recibido',
    )
    fechaRegistro = models.DateTimeField(
        auto_now_add=True, null=True, db_column='fecha_registro',
    )
    fechaModificacion = models.DateTimeField(
        auto_now=True, null=True, db_column='fecha_modificacion',
    )
    idUsuarioRegistra = models.IntegerField(
        null=True, blank=True, db_column='usuario_registra_id',
    )
    idUsuarioModifica = models.IntegerField(
        null=True, blank=True, db_column='usuario_modifica_id',
    )
    activo = models.IntegerField(default=1)

    def __str__(self):
        return f"Turnado {self.pk} – {self.idFus}"


class Seguimiento(models.Model):
    """Respuestas y actividades de seguimiento registradas por ROL2 (CU-06, RN-03)."""

    class Meta:
        db_table = 'scs_tbl_respuestas'
        ordering = ['fechaRegistro']

    idTurnado = models.ForeignKey(
        Turnado, on_delete=models.CASCADE, related_name='seguimientos',
        db_column='turnado_id',
    )
    fechaActividad = models.DateField(
        null=True, blank=True, db_column='fecha_actividad',
    )
    descripcionActividad = models.TextField(
        db_column='descripcion_actividad',
    )
    accionTexto = models.CharField(
        max_length=500, null=True, blank=True, db_column='accion_texto',
    )
    fechaRegistro = models.DateTimeField(
        auto_now_add=True, null=True, db_column='fecha_registro',
    )
    fechaModificacion = models.DateTimeField(
        auto_now=True, null=True, db_column='fecha_modificacion',
    )
    idUsuarioRegistra = models.IntegerField(
        null=True, blank=True, db_column='usuario_registra_id',
    )
    idUsuarioModifica = models.IntegerField(
        null=True, blank=True, db_column='usuario_modifica_id',
    )
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

    fusFolio = models.CharField(max_length=100, null=True, blank=True, db_column='fus_folio')
    fechaHora = models.DateTimeField(auto_now_add=True, db_column='fecha_hora')
    usuario = models.CharField(max_length=255)
    rol = models.CharField(max_length=50)
    accion = models.CharField(max_length=30, choices=ACCION_CHOICES)
    estadoAnterior = models.CharField(max_length=50, null=True, blank=True, db_column='estado_anterior')
    estadoNuevo = models.CharField(max_length=50, null=True, blank=True, db_column='estado_nuevo')
    ipCliente = models.GenericIPAddressField(null=True, blank=True, db_column='ip_cliente')
    observaciones = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.fechaHora} | {self.usuario} | {self.accion} | {self.fusFolio}"


class Notificacion(models.Model):
    """Notificaciones internas del sistema por evento de FUS (sección 5)."""

    class Meta:
        db_table = 'scs_tbl_notificaciones'
        indexes = [
            models.Index(fields=['idDestinatario', 'leida'], name='idx_notif_dest_leida'),
        ]

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
        User, on_delete=models.CASCADE, related_name='notificaciones',
        db_column='destinatario_id'
    )
    fusFolio = models.CharField(max_length=100, db_column='fus_folio')
    tipoEvento = models.CharField(max_length=25, choices=TIPO_CHOICES, db_column='tipo_evento')
    mensaje = models.TextField()
    fechaGeneracion = models.DateTimeField(auto_now_add=True, db_column='fecha_generacion')
    leida = models.IntegerField(default=0)
    fechaLectura = models.DateTimeField(null=True, blank=True, db_column='fecha_lectura')

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
    horaInicio = models.TimeField(db_column='hora_inicio')
    horaFin = models.TimeField(db_column='hora_fin')
    descripcion = models.TextField(blank=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='reunion')
    idCreador = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='actividades_creadas',
        db_column='creador_id'
    )
    idFusRelacionado = models.ForeignKey(
        FUS, on_delete=models.SET_NULL, null=True, blank=True,
        db_column='fus_relacionado_id'
    )
    participantes = models.ManyToManyField(
        User,
        related_name='actividades_invitado',
        blank=True,
        db_table='scs_rel_actividad_participantes',
    )
    fechaCreacion = models.DateTimeField(auto_now_add=True, db_column='fecha_creacion')
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
        indexes = [
            models.Index(fields=['idFus', 'fechaRegistro'], name='idx_seg_fus_fecha'),
        ]

    TIPO_CHOICES = [
        ('accion_por_emprender', 'Acción por emprender'),
        ('avance', 'Avance'),
        ('finalizacion', 'Finalización'),
        ('rechazo', 'Rechazo'),
    ]

    idFus = models.ForeignKey(
        FUS, on_delete=models.CASCADE, related_name='seguimientosComisionado',
        db_column='fus_id'
    )
    idAutor = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='seguimientos_comisionado',
        db_column='autor_id'
    )
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
    contenido = models.TextField()
    fechaRegistro = models.DateTimeField(auto_now_add=True, db_column='fecha_registro')
    activo = models.SmallIntegerField(default=1)

    def __str__(self):
        return f"{self.idFus.folio} — {self.tipo}"


class ReporteGuardado(models.Model):
    """Snapshot inmutable de un reporte exportado por un usuario."""

    class Meta:
        db_table = 'scs_tbl_reportes_guardados'
        ordering = ['-fechaCreacion']

    FORMATO_CHOICES = [
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
        ('pptx', 'Presentación'),
    ]

    idUsuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='reportes_guardados',
        db_column='usuario_id',
    )
    nombre = models.CharField(max_length=200)
    formato = models.CharField(max_length=10, choices=FORMATO_CHOICES)
    filtros = models.JSONField(default=dict, blank=True)
    secciones = models.JSONField(default=list, blank=True)
    nombreArchivo = models.CharField(max_length=255, db_column='nombre_archivo')
    rutaArchivo = models.CharField(max_length=500, db_column='ruta_archivo')
    fechaCreacion = models.DateTimeField(auto_now_add=True, db_column='fecha_creacion')

    def __str__(self):
        return f"{self.nombre} ({self.formato})"
