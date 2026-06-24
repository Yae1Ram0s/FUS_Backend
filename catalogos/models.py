from django.db import models


class MedioRecepcion(models.Model):
    class Meta:
        db_table = 'scs_cat_medios_recepcion'

    nombreMedio = models.CharField(max_length=255, null=True, blank=True)
    paraTurnado = models.IntegerField(default=0)
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return self.nombreMedio or ''


class PrioridadCriterio(models.Model):
    class Meta:
        db_table = 'scs_cat_prioridad_criterios'

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
