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
    """Encola/dispara el envío de UNA notificación — ver notificar_por_correo_lote,
    que hace lo mismo para varias notificaciones del mismo FUS a la vez
    (turnar a N destinatarios) sin repetir la consulta al FUS por cada una."""
    notificar_por_correo_lote([notificacion])


def notificar_por_correo_lote(notificaciones):
    """Encola el envío (django-rq, si REDIS_URL está definido) o lo dispara
    en un hilo aparte (respaldo sin Redis) y regresa de inmediato. El envío
    puede tardar varios segundos (generación del PDF adjunto + handshake
    SMTP) y no hay razón para que la vista que disparó la notificación
    —turnar, comisionar, atender, concluir...— espere eso antes de responder
    al usuario; antes esto corría en línea y era la causa principal de que
    turnar un FUS a varios Titulares se sintiera lento.

    Pensada para varias notificaciones creadas en la MISMA acción (ej. turnar
    un FUS a N destinatarios): se encola/dispara un único trabajo que
    procesa todo el lote junto, así la consulta al FUS con su
    select_related/prefetch_related se hace una sola vez y no una vez por
    destinatario (Hallazgo 3.2 de la auditoría — antes turnar a 5 Titulares
    disparaba 5 hilos, cada uno con su propia consulta completa al FUS). El
    PDF adjunto sigue generándose por separado para cada destinatario: no es
    el mismo documento — cada uno solo debe ver sus propios turnados/
    respuestas, nunca los de otro destinatario turnado al mismo FUS.

    Con la cola real (RQ_QUEUES configurado): 3 reintentos con backoff
    (10s/30s/60s) si el envío falla — antes un fallo (SMTP caído, PDF que no
    se pudo generar) solo quedaba registrado en el log, sin reintento
    automático ni forma de verlo desde la UI."""
    notificaciones = [n for n in notificaciones if n is not None]
    if not notificaciones:
        return
    ids = [n.id for n in notificaciones]
    # `on_commit` (no encolar/arrancar el hilo directo): la mayoría de las
    # vistas que llaman a esto (turnar, comisionar, atender, concluir) están
    # envueltas en `@transaction.atomic` con `select_for_update()`. Si el
    # trabajo arranca antes del commit, corre en OTRA conexión que no ve esa
    # transacción todavía abierta: el `Notificacion.objects.filter(...)` de
    # abajo no encuentra nada (o ve datos viejos, según el motor) aunque las
    # notificaciones ya se hayan guardado bien. `on_commit` difiere el
    # arranque hasta que la transacción de la vista ya cerró — y si la vista
    # NO está en una transacción explícita (autocommit), Django lo ejecuta de
    # inmediato, así que no cambia nada para esos casos.
    if getattr(settings, 'RQ_QUEUES', None):
        import django_rq
        from rq import Retry
        transaction.on_commit(
            lambda: django_rq.get_queue().enqueue(
                _enviar_correos_lote, ids,
                retry=Retry(max=3, interval=[10, 30, 60]),
            )
        )
    else:
        transaction.on_commit(
            lambda: threading.Thread(target=_enviar_correos_lote, args=(ids,), daemon=True).start()
        )


def _cargar_fus_para_correo(folio):
    from ..models import FUS
    return FUS.objects.select_related(
        'idSolicitanteInterno',
        'idMedioRecepcion',
        'estatusParticular',
    ).prefetch_related(
        'evidencias',
        'turnados__idDestinatario',
        'turnados__idMedio',
        'turnados__seguimientos',
    ).get(folio=folio, activo=1)


def _enviar_correos_lote(notificacion_ids):
    # Se reciben ids (no los objetos) a propósito: tanto el hilo suelto de
    # respaldo como, sobre todo, el trabajo encolado en RQ pueden ejecutarse
    # segundos o minutos después de armar las notificaciones, en un proceso
    # aparte (el worker) — reusar las instancias originales arriesga operar
    # sobre objetos desconectados o desactualizados; recargarlas aquí siempre
    # trae el estado real al momento de enviar.
    try:
        from ..models import Notificacion
        notificaciones = list(
            Notificacion.objects.filter(pk__in=notificacion_ids).select_related('idDestinatario')
        )
        # Cache del FUS por folio dentro de este lote — normalmente todas las
        # notificaciones del lote comparten el mismo FUS (turnar a N
        # destinatarios), así que en el caso común esto es una sola consulta
        # para todo el lote, no una por destinatario.
        fus_por_folio = {}
        for notificacion in notificaciones:
            destinatario = notificacion.idDestinatario
            if not destinatario or not destinatario.email:
                continue
            fus = None
            folio = notificacion.fusFolio
            if folio:
                if folio not in fus_por_folio:
                    try:
                        fus_por_folio[folio] = _cargar_fus_para_correo(folio)
                    except Exception:
                        logger.exception(
                            'No se pudo cargar el FUS %s para el lote de correos', folio,
                        )
                        fus_por_folio[folio] = None
                fus = fus_por_folio[folio]
            _enviar_correo_a(notificacion, destinatario, fus=fus)
    finally:
        # Django solo cierra las conexiones a BD automáticamente al final de
        # un request/response normal — en un hilo o worker levantado aparte
        # hay que hacerlo explícito, o cada envío deja una conexión huérfana
        # abierta.
        connections.close_all()


def _enviar_correo_a(notificacion, destinatario, fus=None):
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
                from ..views.fus import generar_pdf_fus

                # `fus` ya viene cargado cuando este envío es parte de un
                # lote (ver _enviar_correos_lote) — evita repetir la misma
                # consulta con select_related/prefetch_related por cada
                # destinatario del mismo FUS.
                if fus is None:
                    fus = _cargar_fus_para_correo(notificacion.fusFolio)
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
