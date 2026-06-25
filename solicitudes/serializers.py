from rest_framework import serializers
from django.contrib.auth.models import User
from catalogos.models import MedioRecepcion
from .models import FUS, SolicitanteExterno, Evidencia, Turnado, Seguimiento, Accion, Notificacion


class UserMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model  = User
        fields = ['id', 'first_name', 'last_name', 'email']


class MedioMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model  = MedioRecepcion
        fields = ['id', 'nombreMedio']


class SolicitanteExternoSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SolicitanteExterno
        fields = ['nombre', 'telefono', 'correo']


class EvidenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Evidencia
        fields = ['id', 'nombreArchivo', 'tipoMime', 'fechaCarga', 'rutaArchivo']


class FUSSerializer(serializers.ModelSerializer):
    idSolicitanteInterno = UserMiniSerializer(read_only=True)
    idMedioRecepcion     = MedioMiniSerializer(read_only=True)
    solicitante_externo  = SolicitanteExternoSerializer(read_only=True)
    evidencias           = EvidenciaSerializer(many=True, read_only=True)

    class Meta:
        model  = FUS
        fields = [
            'id', 'folio', 'idSolicitanteInterno', 'fechaHora',
            'descripcion', 'contexto', 'idMedioRecepcion', 'medioEspecificacion',
            'prioridad', 'estatusParticular', 'fechaConclusion',
            'solicitante_externo', 'evidencias',
        ]


class SeguimientoSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Seguimiento
        fields = ['id', 'fechaActividad', 'descripcionActividad', 'accionTexto']


class AccionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Accion
        fields = ['id', 'numeroOrden', 'descripcion', 'completada']


class NotificacionSerializer(serializers.ModelSerializer):
    tipo          = serializers.CharField(source='tipoEvento')
    fechaCreacion = serializers.DateTimeField(source='fechaGeneracion')

    class Meta:
        model  = Notificacion
        fields = ['id', 'fusFolio', 'tipo', 'mensaje', 'leida', 'fechaCreacion']


class TurnadoSerializer(serializers.ModelSerializer):
    idFus          = FUSSerializer(read_only=True)
    idRemitente    = UserMiniSerializer(read_only=True)
    idDestinatario = UserMiniSerializer(read_only=True)
    idMedio        = MedioMiniSerializer(read_only=True)

    class Meta:
        model  = Turnado
        fields = [
            'id', 'idFus', 'idRemitente', 'idDestinatario',
            'idMedio', 'solicitudTexto', 'fechaHoraTurnado', 'estatusTitular',
        ]


class TurnadoActividadSerializer(serializers.ModelSerializer):
    idDestinatario = UserMiniSerializer(read_only=True)
    idRemitente    = UserMiniSerializer(read_only=True)
    idMedio        = MedioMiniSerializer(read_only=True)
    seguimientos   = SeguimientoSerializer(many=True, read_only=True)
    acciones       = AccionSerializer(many=True, read_only=True)

    class Meta:
        model  = Turnado
        fields = [
            'id', 'idDestinatario', 'idRemitente', 'idMedio',
            'solicitudTexto', 'fechaHoraTurnado', 'estatusTitular',
            'seguimientos', 'acciones',
        ]
