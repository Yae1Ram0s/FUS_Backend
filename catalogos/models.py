from django.db import models


class Estatus(models.Model):
    class Meta:
        db_table = 'scs_tbl_estatus'
        ordering = ['orden']

    TIPO_FLUJO_CHOICES = [
        ('PARTICULAR', 'Particular (ROL1 – FUS)'),
        ('TITULAR',    'Titular (ROL2 – Turnado)'),
        ('AMBOS',      'Ambos flujos'),
    ]

    clave             = models.CharField(max_length=20, unique=True)
    nombre            = models.CharField(max_length=60)
    tipoFlujo         = models.CharField(max_length=12, choices=TIPO_FLUJO_CHOICES)
    orden             = models.PositiveSmallIntegerField(default=0)
    fechaRegistro     = models.DateTimeField(auto_now_add=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activa            = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nombre} ({self.tipoFlujo})"


class MedioRecepcion(models.Model):
    class Meta:
        db_table = 'scs_cat_medios'

    nombreMedio = models.CharField(max_length=255, null=True, blank=True)
    paraTurnado = models.IntegerField(default=0)
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return self.nombreMedio or ''


class UnidadAdministrativa(models.Model):
    """Catálogo institucional de unidades administrativas y aduanas (tabla preexistente)."""

    class Meta:
        db_table = 'scg_cat_unidad_administrativa'
        managed = False
        ordering = ['clave']

    idUnidadAdministrativa = models.AutoField(primary_key=True, db_column='idUnidadAdministrativa')
    clave = models.CharField(max_length=50, null=True, blank=True)
    unidadAdministrativa = models.CharField(max_length=255, null=True, blank=True)
    esUnidadAdministrativa = models.IntegerField(default=0)
    esUnidadDeNegocio = models.IntegerField(default=0)
    fechaRegistro = models.CharField(max_length=50, null=True, blank=True)
    fechaModificacion = models.CharField(max_length=50, null=True, blank=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return self.unidadAdministrativa or ''


class PrioridadCriterio(models.Model):
    class Meta:
        db_table = 'scs_cat_prioridad'

    NIVEL_CHOICES = [
        ('Alta', 'Alta'),
        ('Media', 'Media'),
        ('Baja', 'Baja'),
    ]

    nivel = models.CharField(max_length=10, choices=NIVEL_CHOICES)
    descripcionCriterio = models.TextField()
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.nivel} - {self.descripcionCriterio[:60]}"
