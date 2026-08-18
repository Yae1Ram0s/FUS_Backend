import uuid

from django.contrib.auth.models import User
from django.db import models


class EventoUso(models.Model):
    """Telemetría funcional; es independiente de la bitácora de auditoría."""

    class Resultado(models.TextChoices):
        RECORDED = 'RECORDED', 'Registrado'
        STARTED = 'STARTED', 'Iniciado'
        SUBMITTED = 'SUBMITTED', 'Enviado'
        COMPLETED = 'COMPLETED', 'Completado'
        FAILED = 'FAILED', 'Fallido'
        ABANDONED = 'ABANDONED', 'Abandonado'

    class Dispositivo(models.TextChoices):
        ESCRITORIO = 'ESCRITORIO', 'Escritorio'
        MOVIL = 'MOVIL', 'Móvil'
        TABLETA = 'TABLETA', 'Tableta'
        DESCONOCIDO = 'DESCONOCIDO', 'Desconocido'

    idEvento = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column='id_evento')
    fechaServidor = models.DateTimeField(auto_now_add=True, db_column='fecha_servidor')
    ocurridoEn = models.DateTimeField(null=True, blank=True, db_column='ocurrido_en')
    usuario = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='eventos_uso', db_column='usuario_id',
    )
    rolSnapshot = models.CharField(max_length=30, blank=True, default='', db_column='rol_snapshot')
    unidadSnapshot = models.CharField(max_length=255, blank=True, default='', db_column='unidad_snapshot')
    sesionId = models.CharField(max_length=64, blank=True, default='', db_column='sesion_id')
    modulo = models.CharField(max_length=40)
    componente = models.CharField(max_length=80)
    evento = models.CharField(max_length=40)
    accion = models.CharField(max_length=80, blank=True, default='')
    resultado = models.CharField(max_length=12, choices=Resultado.choices, default=Resultado.RECORDED)
    ruta = models.CharField(max_length=180, blank=True, default='')
    duracionMs = models.PositiveIntegerField(null=True, blank=True, db_column='duracion_ms')
    dispositivo = models.CharField(
        max_length=16, choices=Dispositivo.choices, default=Dispositivo.DESCONOCIDO,
    )
    viewportWidth = models.PositiveSmallIntegerField(null=True, blank=True, db_column='viewport_width')
    appVersion = models.CharField(max_length=40, blank=True, default='', db_column='app_version')
    metadatos = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'scs_analitica_eventos_uso'
        ordering = ['-fechaServidor']
        indexes = [
            models.Index(fields=['-fechaServidor'], name='idx_an_evento_fecha'),
            models.Index(fields=['modulo', '-fechaServidor'], name='idx_an_modulo_fecha'),
            models.Index(fields=['usuario', '-fechaServidor'], name='idx_an_usuario_fecha'),
            models.Index(fields=['rolSnapshot', '-fechaServidor'], name='idx_an_rol_fecha'),
            models.Index(fields=['dispositivo', '-fechaServidor'], name='idx_an_disp_fecha'),
            models.Index(fields=['sesionId', '-fechaServidor'], name='idx_an_sesion_fecha'),
            models.Index(fields=['resultado', '-fechaServidor'], name='idx_an_result_fecha'),
        ]

    def __str__(self):
        return f'{self.modulo}:{self.evento} ({self.idEvento})'
