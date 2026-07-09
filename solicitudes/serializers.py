from rest_framework import serializers
from django.contrib.auth.models import User
from autenticacion.models import CorreoAutorizado
from catalogos.models import MedioRecepcion
from .models import FUS, Evidencia, Turnado, Seguimiento, Notificacion, Bitacora
from .utils import resolver_nombre


class UserMiniSerializer(serializers.ModelSerializer):
    nombre = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = ['id', 'first_name', 'last_name', 'email', 'nombre']

    def get_nombre(self, obj):
        return resolver_nombre(obj)


class MedioMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model  = MedioRecepcion
        fields = ['id', 'nombreMedio']


class EvidenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Evidencia
        fields = ['id', 'nombreArchivo', 'tipoMime', 'fechaCarga', 'rutaArchivo', 'comentarios']


class FUSSerializer(serializers.ModelSerializer):
    idSolicitanteInterno = UserMiniSerializer(read_only=True)
    idMedioRecepcion     = MedioMiniSerializer(read_only=True)
    evidencias           = EvidenciaSerializer(many=True, read_only=True)
    # Devuelve la clave (string) del FK, igual que antes cuando era CharField
    estatusParticular    = serializers.CharField(source='estatusParticular_id', read_only=True)

    class Meta:
        model  = FUS
        fields = [
            'id', 'folio', 'idSolicitanteInterno', 'fechaHora',
            'descripcion', 'contexto', 'idMedioRecepcion', 'medioEspecificacion',
            'prioridad', 'criterios', 'estatusParticular', 'fechaConclusion',
            'nombreExterno', 'telefonoExterno', 'correoExterno', 'evidencias',
        ]


class SeguimientoSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Seguimiento
        fields = ['id', 'fechaActividad', 'descripcionActividad', 'accionTexto']



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
    estatusTitular = serializers.CharField(source='estatusTitular_id', read_only=True)

    class Meta:
        model  = Turnado
        fields = [
            'id', 'idFus', 'idRemitente', 'idDestinatario',
            'idMedio', 'solicitudTexto', 'fechaHoraTurnado', 'estatusTitular',
        ]


class BitacoraSerializer(serializers.ModelSerializer):
    nombre = serializers.SerializerMethodField()
    unidadAdministrativa = serializers.SerializerMethodField()

    def get_nombre(self, obj):
        return self.context.get('nombres_map', {}).get(obj.usuario, '')

    def get_unidadAdministrativa(self, obj):
        autorizado = CorreoAutorizado.objects.select_related('unidadAdministrativa').filter(email=obj.usuario).first()
        if autorizado and autorizado.unidadAdministrativa_id:
            return autorizado.unidadAdministrativa.unidadAdministrativa
        return None

    class Meta:
        model  = Bitacora
        fields = ['id', 'fusFolio', 'fechaHora', 'usuario', 'nombre', 'rol', 'accion',
                  'estadoAnterior', 'estadoNuevo', 'ipCliente', 'observaciones', 'unidadAdministrativa']


class TurnadoActividadSerializer(serializers.ModelSerializer):
    idDestinatario = UserMiniSerializer(read_only=True)
    idRemitente    = UserMiniSerializer(read_only=True)
    idMedio        = MedioMiniSerializer(read_only=True)
    seguimientos   = SeguimientoSerializer(many=True, read_only=True)
    estatusTitular = serializers.CharField(source='estatusTitular_id', read_only=True)

    class Meta:
        model  = Turnado
        fields = [
            'id', 'idDestinatario', 'idRemitente', 'idMedio',
            'solicitudTexto', 'fechaHoraTurnado', 'estatusTitular',
            'seguimientos',
        ]
