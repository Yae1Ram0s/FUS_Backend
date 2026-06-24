from django.contrib import admin
from .models import MedioRecepcion, PrioridadCriterio


@admin.register(MedioRecepcion)
class MedioRecepcionAdmin(admin.ModelAdmin):
    list_display = ['id', 'nombreMedio', 'paraTurnado', 'activo', 'fechaRegistro', 'fechaModificacion']
    list_filter = ['activo', 'paraTurnado']


@admin.register(PrioridadCriterio)
class PrioridadCriterioAdmin(admin.ModelAdmin):
    list_display = ['id', 'nivel', 'descripcionCriterio', 'activo', 'fechaRegistro', 'fechaModificacion']
    list_filter = ['activo', 'nivel']
