import logging
import threading
from urllib.parse import urlencode

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import connections, transaction
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
    """Publica una notificación interna en el canal del destinatario, sin
    interrumpir el flujo si el channel layer falla (mismo criterio que
    notificar_por_correo). Sin este try/except, un fallo aquí —p. ej. Redis
    caído o un hiccup transitorio— tumbaba con un 500 la vista que apenas
    acababa de guardar la transición de estatus (turnar, comisionar, atender,
    concluir...), aunque el cambio ya estuviera comprometido en BD: el
    usuario veía "error" en una acción que en realidad sí se aplicó."""
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
    try:
        async_to_sync(channel_layer.group_send)(
            f'notificaciones_{notificacion.idDestinatario_id}',
            {'type': 'nueva_notificacion', 'data': data},
        )
    except Exception:
        logger.exception(
            'No se pudo publicar la notificación %s en el channel layer',
            notificacion.id,
        )


def notificar_por_correo(notificacion):
    """Dispara el envío en un hilo aparte y regresa de inmediato. El envío
    puede tardar varios segundos (generación del PDF adjunto + handshake
    SMTP) y no hay razón para que la vista que disparó la notificación
    —turnar, comisionar, atender, concluir...— espere eso antes de responder
    al usuario; antes esto corría en línea y era la causa principal de que
    turnar un FUS a varios Titulares se sintiera lento.

    Contraparte: un fallo de envío (SMTP caído, PDF que no se pudo generar)
    solo queda registrado en el log de `_enviar_correo` — sin reintento
    automático ni forma de verlo desde la UI. Si eso llega a ser un problema
    real, el siguiente paso es una cola de tareas de verdad (django-rq sobre
    el mismo Redis que ya usan los Channels), no otro hilo suelto."""
    # `on_commit` (no arrancar el hilo directo): la mayoría de las vistas que
    # llaman a esto (turnar, comisionar, atender, concluir) están envueltas
    # en `@transaction.atomic` con `select_for_update()`. Si el hilo arranca
    # antes del commit, corre en OTRA conexión que no ve esa transacción
    # todavía abierta: el `FUS.objects.get(...)` de abajo le sale
    # `DoesNotExist` (o datos viejos, según el motor) aunque el turnado ya se
    # haya guardado bien. `on_commit` difiere el arranque del hilo hasta que
    # la transacción de la vista ya cerró — y si la vista NO está en una
    # transacción explícita (autocommit), Django lo ejecuta de inmediato, así
    # que no cambia nada para esos casos.
    transaction.on_commit(
        lambda: threading.Thread(target=_enviar_correo, args=(notificacion,), daemon=True).start()
    )


def _enviar_correo(notificacion):
    try:
        destinatario = notificacion.idDestinatario
        if not destinatario or not destinatario.email:
            return
        _enviar_correo_a(notificacion, destinatario)
    finally:
        # Django solo cierra las conexiones a BD automáticamente al final de
        # un request/response normal — en un hilo levantado a mano hay que
        # hacerlo explícito, o cada envío deja una conexión huérfana abierta.
        connections.close_all()


def _enviar_correo_a(notificacion, destinatario):
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

        # Una notificación sin FUS asociado (p. ej. un aviso de calendario
        # para una reunión simple, `fusFolio=''`) no tiene PDF que adjuntar.
        # Sin este corte, cada una de estas disparaba `FUS.objects.get('')`,
        # fallaba con `DoesNotExist` y se registraba como excepción completa
        # en el log — puro ruido, sin ningún caso real que cubrir.
        if notificacion.fusFolio:
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
                    # Igual que en la descarga manual: si el FUS se turnó a
                    # más de un Titular, el PDF adjunto al correo de cada uno
                    # debe acotarse a sus propios turnados/respuestas, nunca
                    # a los de otro destinatario.
                    solo_destinatario_id=destinatario.id if rol == 'ROL2' else None,
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
