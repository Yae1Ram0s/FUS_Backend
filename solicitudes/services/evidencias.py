import hashlib
import json
import os
import uuid

from django.conf import settings
from django.db.models import Sum
from rest_framework import status
from rest_framework.response import Response

from ..models import Evidencia

ALLOWED_MIME_TYPES = {
    'application/pdf',
    'image/jpeg',
    'image/png',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}
ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.docx'}
MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_TOTAL_SIZE = 30 * 1024 * 1024


def _validar_archivo(archivo):
    extension = os.path.splitext(archivo.name)[1].lower()
    mime = (archivo.content_type or '').split(';')[0].strip()
    if extension not in ALLOWED_EXTENSIONS:
        return f'Extensión no permitida: {extension}. Usa PDF, JPG, PNG o DOCX.'
    if mime and mime not in ALLOWED_MIME_TYPES:
        return f'Tipo de archivo no permitido: {mime}.'
    if archivo.size > MAX_FILE_SIZE:
        return f'"{archivo.name}" supera 10 MB.'
    return None


def _sha256(archivo):
    digest = hashlib.sha256()
    for chunk in archivo.chunks():
        digest.update(chunk)
    return digest.hexdigest()


def guardar_evidencias(fus, request, user):
    """Valida y guarda evidencias; devuelve una respuesta solamente si falla."""
    archivos = request.FILES.getlist('evidencias')
    if not archivos:
        return None

    # RN-09: 30 MB por FUS, acumulado — no solo lo que trae este request. Un
    # FUS editable (estatus 'Registrado') admite varias subidas por separado
    # (crear, luego editar y adjuntar más), así que hay que sumar lo que ya
    # tiene guardado en BD o el tope se puede rebasar en varias pasadas.
    ya_guardado = fus.evidencias.filter(activo=1).aggregate(
        total=Sum('tamanoBytes')
    )['total'] or 0
    if ya_guardado + sum(archivo.size for archivo in archivos) > MAX_TOTAL_SIZE:
        return Response(
            {'detail': 'El total de archivos (incluyendo evidencia ya guardada) supera 30 MB.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    for archivo in archivos:
        error = _validar_archivo(archivo)
        if error:
            return Response(
                {'detail': error},
                status=status.HTTP_400_BAD_REQUEST,
            )

    try:
        comentarios = json.loads(
            request.data.get('comentariosEvidencias') or '[]'
        )
    except (ValueError, TypeError):
        comentarios = []

    for indice, archivo in enumerate(archivos):
        nombre_seguro = os.path.basename(archivo.name)
        nombre_fisico = f'{uuid.uuid4().hex}_{nombre_seguro}'
        ruta_relativa = f'evidencias/{fus.pk}/{nombre_fisico}'
        ruta_absoluta = os.path.join(settings.MEDIA_ROOT, ruta_relativa)
        os.makedirs(os.path.dirname(ruta_absoluta), exist_ok=True)

        hash_sha256 = _sha256(archivo)
        with open(ruta_absoluta, 'wb') as destino:
            for chunk in archivo.chunks():
                destino.write(chunk)

        comentario = (
            comentarios[indice].strip()
            if indice < len(comentarios) and comentarios[indice]
            else None
        )
        Evidencia.objects.create(
            idFus=fus,
            nombreArchivo=nombre_seguro,
            rutaArchivo=ruta_relativa,
            tipoMime=archivo.content_type,
            hashSha256=hash_sha256,
            tamanoBytes=archivo.size,
            comentarios=comentario,
            idUsuarioRegistra=user.id,
        )

    return None
