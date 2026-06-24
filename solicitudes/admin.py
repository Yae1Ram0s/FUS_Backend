from django.contrib import admin
from .models import FUS, SolicitanteExterno, Evidencia, Turnado, Seguimiento, Accion, Bitacora, Notificacion


@admin.register(FUS)
class FUSAdmin(admin.ModelAdmin):
    list_display = ['folio', 'idSolicitanteInterno', 'prioridad', 'estatusParticular', 'fechaHora', 'activo']
    list_filter = ['activo', 'estatusParticular', 'prioridad']
    search_fields = ['folio']


@admin.register(SolicitanteExterno)
class SolicitanteExternoAdmin(admin.ModelAdmin):
    list_display = ['id', 'idFus', 'nombre', 'telefono', 'correo', 'activo']
    list_filter = ['activo']


@admin.register(Evidencia)
class EvidenciaAdmin(admin.ModelAdmin):
    list_display = ['id', 'idFus', 'nombreArchivo', 'tipoMime', 'hashSha256', 'fechaCarga', 'activo']
    list_filter = ['activo', 'tipoMime']


@admin.register(Turnado)
class TurnadoAdmin(admin.ModelAdmin):
    list_display = ['id', 'idFus', 'idRemitente', 'idDestinatario', 'estatusTitular', 'fechaHoraTurnado', 'activo']
    list_filter = ['activo', 'estatusTitular']


@admin.register(Seguimiento)
class SeguimientoAdmin(admin.ModelAdmin):
    list_display = ['id', 'idTurnado', 'fechaActividad', 'activo']
    list_filter = ['activo']


@admin.register(Accion)
class AccionAdmin(admin.ModelAdmin):
    list_display = ['id', 'idTurnado', 'numeroOrden', 'completada', 'activo']
    list_filter = ['activo', 'completada']


@admin.register(Bitacora)
class BitacoraAdmin(admin.ModelAdmin):
    list_display = ['fechaHora', 'usuario', 'rol', 'accion', 'fusFolio', 'estadoAnterior', 'estadoNuevo', 'ipCliente']
    list_filter = ['accion', 'rol']
    search_fields = ['fusFolio', 'usuario']
    readonly_fields = [f.name for f in Bitacora._meta.get_fields()]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ['id', 'idDestinatario', 'fusFolio', 'tipoEvento', 'leida', 'fechaGeneracion', 'fechaLectura']
    list_filter = ['tipoEvento', 'leida']
    search_fields = ['fusFolio']
