from django.contrib import admin
from .models import CorreoAutorizado, CodigoOTP


@admin.register(CorreoAutorizado)
class CorreoAutorizadoAdmin(admin.ModelAdmin):
    list_display = ['email', 'nombre', 'rol', 'activo', 'fechaRegistro']
    list_filter = ['activo', 'rol']
    search_fields = ['email', 'nombre']


@admin.register(CodigoOTP)
class CodigoOTPAdmin(admin.ModelAdmin):
    list_display = ['email', 'codigo', 'fechaGeneracion', 'fechaExpiracion', 'usado', 'ipSolicitante']
    list_filter = ['usado']
    search_fields = ['email']
