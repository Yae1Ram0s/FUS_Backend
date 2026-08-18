import json
import re
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from .models import EventoUso
from .taxonomy import ACCIONES, EVENTOS, MODULOS


CLAVE_SEGURA_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{0,39}$')
SLUG_RE = re.compile(r'^[A-Z0-9_.:-]{1,80}$')
EMAIL_RE = re.compile(r'\b[^\s@]+@[^\s@]+\.[^\s@]+\b', re.IGNORECASE)
FOLIO_RE = re.compile(r'\b(?:[A-Z]{2,}(?:/[A-Z0-9_-]+){2,}|FUS[/_-]?\d+)\b', re.IGNORECASE)
CLAVES_PROHIBIDAS = frozenset({
    'email', 'correo', 'nombre', 'apellido', 'telefono', 'celular',
    'descripcion', 'texto', 'comentario', 'mensaje', 'folio', 'fus',
    'password', 'contrasena', 'token', 'authorization', 'cookie',
    'ip', 'direccionip', 'solicitante', 'responsable',
})


def _validar_metadatos(valor, profundidad=0):
    if profundidad > 3:
        raise serializers.ValidationError('Los metadatos exceden la profundidad permitida.')
    if isinstance(valor, dict):
        if len(valor) > 20:
            raise serializers.ValidationError('Los metadatos admiten como máximo 20 claves por nivel.')
        limpio = {}
        for clave, contenido in valor.items():
            clave_texto = str(clave)
            clave_normalizada = re.sub(r'[^a-z0-9]', '', clave_texto.lower())
            if not CLAVE_SEGURA_RE.fullmatch(clave_texto) or clave_normalizada in CLAVES_PROHIBIDAS:
                raise serializers.ValidationError(f'La clave de metadatos "{clave_texto}" no está permitida.')
            limpio[clave_texto] = _validar_metadatos(contenido, profundidad + 1)
        return limpio
    if isinstance(valor, list):
        if len(valor) > 20:
            raise serializers.ValidationError('Las listas de metadatos admiten como máximo 20 elementos.')
        return [_validar_metadatos(item, profundidad + 1) for item in valor]
    if isinstance(valor, str):
        if len(valor) > 100:
            raise serializers.ValidationError('Los textos de metadatos admiten como máximo 100 caracteres.')
        if EMAIL_RE.search(valor) or FOLIO_RE.search(valor):
            raise serializers.ValidationError('Los metadatos no pueden contener correos ni folios.')
        return valor
    if valor is None or isinstance(valor, (bool, int, float)):
        return valor
    raise serializers.ValidationError('Tipo de dato no permitido en metadatos.')


class EventoUsoEntradaSerializer(serializers.ModelSerializer):
    # Aunque el modelo genera UUID para usos internos, en esta API es
    # obligatorio porque funciona como llave de idempotencia del cliente.
    idEvento = serializers.UUIDField()

    class Meta:
        model = EventoUso
        fields = (
            'idEvento', 'ocurridoEn', 'sesionId', 'modulo', 'componente',
            'evento', 'accion', 'resultado', 'ruta', 'duracionMs',
            'dispositivo', 'viewportWidth', 'appVersion', 'metadatos',
        )

    def validate_idEvento(self, value):
        return value

    def validate_ocurridoEn(self, value):
        ahora = timezone.now()
        if value > ahora + timedelta(minutes=5):
            raise serializers.ValidationError('La fecha del evento no puede estar en el futuro.')
        if value < ahora - timedelta(days=30):
            raise serializers.ValidationError('No se aceptan eventos con más de 30 días de antigüedad.')
        return value

    def validate_sesionId(self, value):
        if value and not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', value):
            raise serializers.ValidationError('Identificador de sesión no válido.')
        return value

    def validate_modulo(self, value):
        value = value.upper()
        if value not in MODULOS:
            raise serializers.ValidationError('Módulo fuera de la taxonomía permitida.')
        return value

    def validate_componente(self, value):
        value = value.upper()
        if not SLUG_RE.fullmatch(value):
            raise serializers.ValidationError('El componente debe ser una clave corta en mayúsculas.')
        return value

    def validate_evento(self, value):
        value = value.upper()
        if value not in EVENTOS:
            raise serializers.ValidationError('Evento fuera de la taxonomía permitida.')
        return value

    def validate_accion(self, value):
        value = value.upper()
        if value and value not in ACCIONES:
            raise serializers.ValidationError('Acción fuera de la taxonomía permitida.')
        return value

    def validate_ruta(self, value):
        if value and (not value.startswith('/') or '?' in value or '#' in value):
            raise serializers.ValidationError('La ruta debe ser relativa y no incluir parámetros.')
        if re.search(r'/\d{3,}(?:/|$)', value):
            raise serializers.ValidationError('La ruta no puede contener identificadores de registros.')
        return value

    def validate_duracionMs(self, value):
        if value is not None and value > 3_600_000:
            raise serializers.ValidationError('La duración excede el máximo permitido.')
        return value

    def validate_viewportWidth(self, value):
        if value is not None and not 240 <= value <= 10_000:
            raise serializers.ValidationError('El ancho de pantalla no es válido.')
        return value

    def validate_appVersion(self, value):
        if value and not re.fullmatch(r'[A-Za-z0-9._+-]{1,40}', value):
            raise serializers.ValidationError('Versión de aplicación no válida.')
        return value

    def validate_metadatos(self, value):
        limpio = _validar_metadatos(value)
        if len(json.dumps(limpio, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > 4096:
            raise serializers.ValidationError('Los metadatos exceden 4 KB.')
        return limpio

    def validate(self, attrs):
        evento = attrs.get('evento')
        resultado = attrs.get('resultado', EventoUso.Resultado.RECORDED)
        esperados = {
            'FORM_STARTED': EventoUso.Resultado.STARTED,
            'FORM_SUBMITTED': EventoUso.Resultado.SUBMITTED,
            'FORM_ABANDONED': EventoUso.Resultado.ABANDONED,
            'TASK_STARTED': EventoUso.Resultado.STARTED,
            'TASK_COMPLETED': EventoUso.Resultado.COMPLETED,
            'TASK_FAILED': EventoUso.Resultado.FAILED,
            'TASK_ABANDONED': EventoUso.Resultado.ABANDONED,
        }
        if evento in esperados and resultado != esperados[evento]:
            raise serializers.ValidationError({'resultado': f'Este evento requiere resultado {esperados[evento]}.'})
        return attrs
