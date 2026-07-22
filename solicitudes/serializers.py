from rest_framework import serializers
from django.contrib.auth.models import User
from catalogos.models import MedioRecepcion
from .models import FUS, Evidencia, Turnado, Seguimiento, Notificacion, Bitacora, Actividad, SeguimientoRespuesta
from .utils import resolver_nombre, get_rol
from .helpers import _resolver_unidad_administrativa
from .permissions import _unidad_id


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
    idComisionado        = UserMiniSerializer(read_only=True)
    evidencias           = EvidenciaSerializer(many=True, read_only=True)
    # Devuelve la clave (string) del FK, igual que antes cuando era CharField
    estatusParticular    = serializers.CharField(source='estatusParticular_id', read_only=True)
    slaVencido           = serializers.SerializerMethodField()
    slaPorVencer         = serializers.SerializerMethodField()
    direccionComisionado = serializers.SerializerMethodField()
    tieneTurnado         = serializers.SerializerMethodField()

    class Meta:
        model  = FUS
        fields = [
            'id', 'folio', 'idSolicitanteInterno', 'fechaHora',
            'descripcion', 'contexto', 'idMedioRecepcion', 'medioEspecificacion',
            'prioridad', 'criterios', 'estatusParticular', 'fechaConclusion',
            'nombreExterno', 'telefonoExterno', 'correoExterno', 'evidencias',
            'fechaLimite', 'slaVencido', 'slaPorVencer',
            'idComisionado', 'fechaAsignacion', 'direccionComisionado', 'tieneTurnado',
        ]

    def get_direccionComisionado(self, obj):
        if not obj.idComisionado_id:
            return None
        return _resolver_unidad_administrativa(obj.idComisionado)

    def get_tieneTurnado(self, obj):
        # True si el FUS pasó por el flujo de Titular (se turnó a un ROL2)
        # antes de comisionarse, aunque sea a otra dirección — false si el
        # Particular lo comisionó directo desde "Registrado".
        return obj.turnados.filter(activo=1).exists()

    def get_slaVencido(self, obj):
        from django.utils import timezone
        if obj.estatusParticular_id != 'Turnado' or not obj.fechaLimite:
            return False
        return timezone.now() > obj.fechaLimite

    def get_slaPorVencer(self, obj):
        from datetime import timedelta
        from django.utils import timezone
        if obj.estatusParticular_id != 'Turnado' or not obj.fechaLimite:
            return False
        faltante = obj.fechaLimite - timezone.now()
        return timedelta(0) < faltante <= timedelta(hours=24)


class SeguimientoSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Seguimiento
        fields = ['id', 'fechaActividad', 'descripcionActividad', 'accionTexto', 'fechaRegistro']


class SeguimientoRespuestaSerializer(serializers.ModelSerializer):
    idAutor = UserMiniSerializer(read_only=True)

    class Meta:
        model  = SeguimientoRespuesta
        fields = ['id', 'idFus', 'idAutor', 'tipo', 'contenido', 'fechaRegistro']
        read_only_fields = ['idFus', 'idAutor', 'fechaRegistro']

    def validate_contenido(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('El contenido no puede estar vacío.')
        return value


class SeguimientoComisionadoCreateSerializer(SeguimientoRespuestaSerializer):
    """POST seguimiento del Comisionado: restringe `tipo` a los valores que el
    Comisionado puede reportar (la finalización/rechazo ya no las genera él,
    las produce el flujo de atendido/validación) y valida que el FUS siga en
    curso. 'En_seguimiento' = aún sin ninguna respuesta; 'Atendido' = ya tiene
    al menos una; 'Rechazado' = el Particular la rechazó y esta respuesta es
    la que la reabre directo a 'Atendido' (ver la vista). Todas admiten
    seguir agregando respuestas. Requiere `fus` en el context."""

    TIPOS_PERMITIDOS = ('accion_por_emprender', 'avance')
    ESTATUS_PERMITIDOS = ('En_seguimiento', 'Atendido', 'Rechazado')

    class Meta(SeguimientoRespuestaSerializer.Meta):
        fields = ['tipo', 'contenido']

    def validate_tipo(self, value):
        if value not in self.TIPOS_PERMITIDOS:
            raise serializers.ValidationError('Tipo de seguimiento inválido.')
        return value

    def validate(self, attrs):
        fus = self.context['fus']
        if fus.estatusParticular_id not in self.ESTATUS_PERMITIDOS:
            raise serializers.ValidationError(
                'Solo se puede dar seguimiento mientras la solicitud está en seguimiento.'
            )
        return attrs


class ComisionarFUSSerializer(serializers.Serializer):
    """Valida la transición de estatus y que el comisionado elegido
    pertenezca a la misma dirección/unidad de quien comisiona.

    Rol 1 comisiona directo desde 'Registrado' (sin turnado de por medio).
    Rol 2 comisiona desde el Turnado que le fue asignado a él específicamente
    (no cualquier Turnado de la dirección), exigiendo que siga 'Recibido' y
    que el FUS siga globalmente en 'Turnado' (evita que dos titulares del
    mismo FUS se pisen si ya fue comisionado por otro). Requiere `request` y
    `fus` en el context."""

    comisionado_id = serializers.IntegerField(required=True)

    def validate(self, attrs):
        request = self.context['request']
        fus     = self.context['fus']
        user    = request.user
        rol     = get_rol(user)

        if fus.estatusParticular_id == 'Concluido':
            raise serializers.ValidationError(
                'La solicitud ya fue concluida y no puede asignarse a un comisionado.'
            )

        if rol == 'ROL1':
            if fus.estatusParticular_id != 'Registrado':
                raise serializers.ValidationError(
                    'La solicitud debe estar en estatus "Registrado" para asignar un comisionado.'
                )
            attrs['turnado'] = None
        else:
            turnado = Turnado.objects.filter(idFus=fus, idDestinatario=user, activo=1).first()
            if fus.estatusParticular_id != 'Turnado' or not turnado or turnado.estatusTitular_id != 'Recibido':
                raise serializers.ValidationError(
                    'La solicitud debe estar en estatus "Turnado" y "Recibido" en tu bandeja para asignar un comisionado.'
                )
            attrs['turnado'] = turnado

        comisionado = User.objects.filter(pk=attrs['comisionado_id']).first()
        if not comisionado:
            raise serializers.ValidationError(
                'Debe seleccionar un comisionado para poder guardar la asignación.'
            )
        if get_rol(comisionado) != 'COMISIONADO' or _unidad_id(comisionado) != _unidad_id(user):
            raise serializers.ValidationError(
                'El comisionado seleccionado no pertenece a tu dirección/unidad administrativa.'
            )

        attrs['comisionado'] = comisionado
        return attrs


class AtendidoFUSSerializer(serializers.Serializer):
    """Confirma el paso a validación — exige que el comisionado ya haya
    registrado al menos una respuesta (estatus 'Atendido', que la vista de
    seguimiento asigna automáticamente en la primera). 'En_seguimiento' solo
    significa "comisionado asignado, aún sin responder": no basta. Requiere
    `fus` en el context."""

    def validate(self, attrs):
        fus = self.context['fus']
        if fus.estatusParticular_id != 'Atendido':
            raise serializers.ValidationError(
                'El comisionado debe registrar al menos una respuesta antes de poder marcarla como atendida.'
            )
        return attrs


def _validable_por_rol1(fus):
    """Pendiente_validacion (turnado a Rol 2, que ya confirmó "Atendido"), o
    directo en 'Atendido' cuando el FUS no tiene turnado — ahí Rol 1
    comisionó de frente, nadie más confirma "Atendido", así que valida sobre
    la primera respuesta del comisionado sin ese paso intermedio."""
    if fus.estatusParticular_id == 'Pendiente_validacion':
        return True
    return fus.estatusParticular_id == 'Atendido' and not fus.turnados.filter(activo=1).exists()


class ConcluirAsuntoSerializer(serializers.Serializer):
    """Valida que el FUS esté listo para concluirse. Requiere `fus` en el
    context."""

    def validate(self, attrs):
        if not _validable_por_rol1(self.context['fus']):
            raise serializers.ValidationError(
                'La solicitud debe estar pendiente de validación para poder aprobarla.'
            )
        return attrs


class RechazarSolicitudSerializer(serializers.Serializer):
    """Valida que el FUS esté listo para rechazarse y que venga un motivo no
    vacío. El efecto (estatus → Rechazado) lo aplica la vista. Requiere `fus`
    en el context."""

    motivo = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        if not _validable_por_rol1(self.context['fus']):
            raise serializers.ValidationError(
                'La solicitud debe estar pendiente de validación para poder rechazarla.'
            )
        motivo = (attrs.get('motivo') or '').strip()
        if not motivo:
            raise serializers.ValidationError('Debes escribir un motivo antes de rechazar.')
        attrs['motivo'] = motivo
        return attrs


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
        user = User.objects.filter(email=obj.usuario).first()
        return _resolver_unidad_administrativa(user) if user else None

    class Meta:
        model  = Bitacora
        fields = ['id', 'fusFolio', 'fechaHora', 'usuario', 'nombre', 'rol', 'accion',
                  'estadoAnterior', 'estadoNuevo', 'ipCliente', 'observaciones', 'unidadAdministrativa']


class ActividadSerializer(serializers.ModelSerializer):
    fusFolio           = serializers.SerializerMethodField()
    participantesInfo  = serializers.SerializerMethodField()

    class Meta:
        model  = Actividad
        fields = [
            'id', 'titulo', 'fecha', 'horaInicio', 'horaFin', 'descripcion', 'tipo',
            'idCreador', 'idFusRelacionado', 'participantes', 'fechaCreacion',
            'fusFolio', 'participantesInfo',
        ]

    def get_fusFolio(self, obj):
        return obj.idFusRelacionado.folio if obj.idFusRelacionado else None

    def get_participantesInfo(self, obj):
        return [
            {'id': u.id, 'nombre': resolver_nombre(u), 'email': u.email}
            for u in obj.participantes.all()
        ]


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
