from django.db import models


class Estatus(models.Model):
    class Meta:
        db_table = 'scs_cat_estatus'
        ordering = ['orden']

    TIPO_FLUJO_CHOICES = [
        ('PARTICULAR', 'Particular (ROL1 – FUS)'),
        ('TITULAR',    'Titular (ROL2 – Turnado)'),
        ('AMBOS',      'Ambos flujos'),
    ]

    clave             = models.CharField(max_length=20, unique=True)
    nombre            = models.CharField(max_length=60)
    tipoFlujo         = models.CharField(max_length=12, choices=TIPO_FLUJO_CHOICES, db_column='tipo_flujo')
    orden             = models.PositiveSmallIntegerField(default=0)
    fechaRegistro     = models.DateTimeField(auto_now_add=True, null=True, db_column='fecha_registro')
    idUsuarioRegistra = models.IntegerField(null=True, blank=True, db_column='usuario_registra_id')
    fechaModificacion = models.DateTimeField(auto_now=True, null=True, db_column='fecha_modificacion')
    idUsuarioModifica = models.IntegerField(null=True, blank=True, db_column='usuario_modifica_id')
    activa            = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nombre} ({self.tipoFlujo})"


class MedioRecepcion(models.Model):
    class Meta:
        db_table = 'scs_cat_medios_recepcion'

    nombreMedio = models.CharField(max_length=255, null=True, blank=True, db_column='nombre_medio')
    paraTurnado = models.IntegerField(default=0, db_column='para_turnado')
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True, db_column='fecha_registro')
    fechaModificacion = models.DateTimeField(auto_now=True, null=True, db_column='fecha_modificacion')
    idUsuarioRegistra = models.IntegerField(null=True, blank=True, db_column='usuario_registra_id')
    idUsuarioModifica = models.IntegerField(null=True, blank=True, db_column='usuario_modifica_id')
    activo = models.IntegerField(default=1)

    def __str__(self):
        return self.nombreMedio or ''


class UnidadAdministrativa(models.Model):
    """Catálogo institucional de unidades administrativas y aduanas (tabla preexistente)."""

    class Meta:
        db_table = 'scs_cat_unidades_administrativas'
        managed = False
        ordering = ['clave']

    # Tabla no administrada por Django (managed=False) — los tipos de abajo
    # reflejan exactamente lo que hay hoy en la columna real, no lo que
    # "debería" ser (ver auditoría: id es int sin autoincrement/PK real,
    # clave/nombre/fechas son text sin límite, y los flags permiten NULL).
    idUnidadAdministrativa = models.IntegerField(primary_key=True, db_column='id')
    clave = models.TextField(null=True, blank=True)
    unidadAdministrativa = models.TextField(null=True, blank=True, db_column='nombre')
    esUnidadAdministrativa = models.IntegerField(default=0, null=True, blank=True, db_column='es_unidad_administrativa')
    esUnidadDeNegocio = models.IntegerField(default=0, null=True, blank=True, db_column='es_unidad_negocio')
    fechaRegistro = models.TextField(null=True, blank=True, db_column='fecha_registro')
    fechaModificacion = models.TextField(null=True, blank=True, db_column='fecha_modificacion')
    idUsuarioRegistra = models.IntegerField(null=True, blank=True, db_column='usuario_registra_id')
    idUsuarioModifica = models.IntegerField(null=True, blank=True, db_column='usuario_modifica_id')
    activo = models.IntegerField(default=1, null=True, blank=True)

    def __str__(self):
        return self.unidadAdministrativa or ''


class PrioridadCriterio(models.Model):
    class Meta:
        db_table = 'scs_cat_criterios_prioridad'

    NIVEL_CHOICES = [
        ('Alta', 'Alta'),
        ('Media', 'Media'),
        ('Baja', 'Baja'),
    ]

    nivel = models.CharField(max_length=10, choices=NIVEL_CHOICES)
    descripcionCriterio = models.TextField(db_column='descripcion_criterio')
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True, db_column='fecha_registro')
    fechaModificacion = models.DateTimeField(auto_now=True, null=True, db_column='fecha_modificacion')
    idUsuarioRegistra = models.IntegerField(null=True, blank=True, db_column='usuario_registra_id')
    idUsuarioModifica = models.IntegerField(null=True, blank=True, db_column='usuario_modifica_id')
    activo = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.nivel} - {self.descripcionCriterio[:60]}"
