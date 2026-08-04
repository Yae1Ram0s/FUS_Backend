import logging
from urllib.parse import urlencode

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape

from ..utils import get_rol

logger = logging.getLogger(__name__)


TIPO_EVENTO_ASUNTO = {
    'TURNADO': 'Nuevo FUS turnado — {folio}',
    'RESPUESTA': 'Nueva respuesta registrada — {folio}',
    'CONCLUIDO': 'FUS concluido — {folio}',
    'SLA_POR_VENCER': 'FUS por vencer — {folio}',
    'ACTIVIDAD': 'Nueva actividad en tu calendario',
    'ASIGNADO_COMISIONADO': 'Se te asignó un FUS — {folio}',
    'SEGUIMIENTO_FINALIZADO': (
        'Seguimiento finalizado, pendiente de validación — {folio}'
    ),
    'SOLICITUD_APROBADA': 'Tu seguimiento fue aprobado — {folio}',
    'SOLICITUD_RECHAZADA': 'Tu seguimiento fue rechazado — {folio}',
}


def push_notificacion(notificacion):
    """Publica una notificación interna en el canal del destinatario."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    data = {
        'id': str(notificacion.id),
        'fusFolio': notificacion.fusFolio,
        'tipo': notificacion.tipoEvento,
        'mensaje': notificacion.mensaje,
        'leida': False,
        'fechaCreacion': notificacion.fechaGeneracion.isoformat(),
    }
    async_to_sync(channel_layer.group_send)(
        f'notificaciones_{notificacion.idDestinatario_id}',
        {'type': 'nueva_notificacion', 'data': data},
    )


def notificar_por_correo(notificacion):
    """Envía una copia por correo sin interrumpir el flujo si el canal falla."""
    destinatario = notificacion.idDestinatario
    if not destinatario or not destinatario.email:
        return

    asunto_template = TIPO_EVENTO_ASUNTO.get(
        notificacion.tipoEvento,
        'Actualización de FUS — {folio}',
    )
    asunto = asunto_template.format(folio=notificacion.fusFolio)

    rol = get_rol(destinatario)
    if rol == 'ROL1':
        ruta = '/rol1/consultar-fus'
    elif rol == 'ROL2':
        ruta = '/rol2/solicitudes'
    else:
        ruta = '/comisionado/fus-comisionados'

    query = urlencode({'modo': 'lista', 'folio': notificacion.fusFolio})
    url_fus = f'{settings.FRONTEND_URL}{ruta}?{query}'
    html_body = (
        f'<p>{escape(notificacion.mensaje)}</p>'
        f'<p>FUS: <a href="{escape(url_fus)}">'
        f'{escape(notificacion.fusFolio)}</a></p>'
    )
    remitente = (
        settings.DEFAULT_FROM_EMAIL
        if hasattr(settings, 'DEFAULT_FROM_EMAIL')
        else settings.EMAIL_HOST_USER
    )

    try:
        email = EmailMultiAlternatives(
            asunto,
            notificacion.mensaje,
            remitente,
            [destinatario.email],
        )
        email.attach_alternative(html_body, 'text/html')

        try:
            from ..models import FUS
            from ..views.fus import generar_pdf_fus

            fus = FUS.objects.select_related(
                'idSolicitanteInterno',
                'idMedioRecepcion',
                'estatusParticular',
            ).prefetch_related(
                'evidencias',
                'turnados__idDestinatario',
                'turnados__idMedio',
                'turnados__seguimientos',
            ).get(folio=notificacion.fusFolio, activo=1)
            pdf_bytes = generar_pdf_fus(
                fus,
                incluir_imagenes=False,
                rol_visor='ROL2' if rol == 'ROL2' else 'ROL1',
            )
            nombre_pdf = f'FUS_{fus.folio.replace("/", "-")}.pdf'
            email.attach(nombre_pdf, pdf_bytes, 'application/pdf')
        except Exception:
            logger.exception(
                'No se pudo adjuntar el PDF del FUS %s al correo',
                notificacion.fusFolio,
            )

        email.send(fail_silently=True)
    except Exception:
        logger.exception(
            'No se pudo enviar correo de notificación a %s',
            destinatario.email,
        )
