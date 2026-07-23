import logging
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from autenticacion.models import CorreoAutorizado

logger = logging.getLogger(__name__)


def _resolver_unidad_administrativa(user):
    autorizado = CorreoAutorizado.objects.select_related('unidadAdministrativa').filter(email=user.email).first()
    if autorizado and autorizado.unidadAdministrativa_id:
        return autorizado.unidadAdministrativa.unidadAdministrativa
    return 'Sin unidad asignada'


TIPO_EVENTO_ASUNTO = {
    'TURNADO':                 'Nuevo FUS turnado — {folio}',
    'RESPUESTA':               'Nueva respuesta registrada — {folio}',
    'CONCLUIDO':               'FUS concluido — {folio}',
    'SLA_POR_VENCER':          'FUS por vencer — {folio}',
    'ACTIVIDAD':               'Nueva actividad en tu calendario',
    'ASIGNADO_COMISIONADO':    'Se te asignó un FUS — {folio}',
    'SEGUIMIENTO_FINALIZADO':  'Seguimiento finalizado, pendiente de validación — {folio}',
    'SOLICITUD_APROBADA':      'Tu seguimiento fue aprobado — {folio}',
    'SOLICITUD_RECHAZADA':     'Tu seguimiento fue rechazado — {folio}',
}


def notificar_por_correo(notificacion):
    """Envía copia por correo de una notificación in-app, con el PDF del FUS
    adjunto y un link al folio que redirige a la vista correspondiente según
    el rol del destinatario. No lanza excepción si falla — el correo es un
    canal adicional, no debe romper el flujo principal."""
    from django.utils.html import escape

    from .utils import get_rol

    dest = notificacion.idDestinatario
    if not dest or not dest.email:
        return

    asunto_tpl = TIPO_EVENTO_ASUNTO.get(notificacion.tipoEvento, 'Actualización de FUS — {folio}')
    asunto = asunto_tpl.format(folio=notificacion.fusFolio)

    rol = get_rol(dest)
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
        f'<p>FUS: <a href="{escape(url_fus)}">{escape(notificacion.fusFolio)}</a></p>'
    )

    remitente = settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else settings.EMAIL_HOST_USER

    try:
        email = EmailMultiAlternatives(asunto, notificacion.mensaje, remitente, [dest.email])
        email.attach_alternative(html_body, 'text/html')

        try:
            from .models import FUS
            from .views.fus import generar_pdf_fus
            fus = FUS.objects.select_related(
                'idSolicitanteInterno', 'idMedioRecepcion', 'estatusParticular'
            ).prefetch_related(
                'evidencias', 'turnados__idDestinatario', 'turnados__idMedio', 'turnados__seguimientos'
            ).get(folio=notificacion.fusFolio, activo=1)
            pdf_bytes = generar_pdf_fus(fus, incluir_imagenes=False, rol_visor='ROL2' if rol == 'ROL2' else 'ROL1')
            email.attach(f'FUS_{fus.folio.replace("/", "-")}.pdf', pdf_bytes, 'application/pdf')
        except Exception:
            logger.exception(f"No se pudo adjuntar el PDF del FUS {notificacion.fusFolio} al correo")

        email.send(fail_silently=True)
    except Exception:
        logger.exception(f"No se pudo enviar correo de notificación a {dest.email}")
