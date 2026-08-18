from django.contrib import admin
from .models import EventoUso


@admin.register(EventoUso)
class EventoUsoAdmin(admin.ModelAdmin):
    list_display = ['fechaServidor', 'modulo', 'componente', 'evento', 'accion', 'resultado', 'usuario', 'dispositivo']
    list_filter = ['modulo', 'evento', 'resultado', 'dispositivo', 'rolSnapshot']
    search_fields = ['modulo', 'componente', 'sesionId', 'usuario__email']
    date_hierarchy = 'fechaServidor'
