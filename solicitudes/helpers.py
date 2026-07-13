import logging

from django.conf import settings
from django.core.mail import send_mail

from autenticacion.models import CorreoAutorizado

logger = logging.getLogger(__name__)


def _resolver_unidad_administrativa(user):
    autorizado = CorreoAutorizado.objects.select_related('unidadAdministrativa').filter(email=user.email).first()
    if autorizado and autorizado.unidadAdministrativa_id:
        return autorizado.unidadAdministrativa.unidadAdministrativa
    return 'Sin unidad asignada'


TIPO_EVENTO_ASUNTO = {
    'TURNADO':    'Nuevo FUS turnado — {folio}',
    'RESPUESTA':  'Nueva respuesta registrada — {folio}',
    'CONCLUIDO':  'FUS concluido — {folio}',
}


def notificar_por_correo(notificacion):
    """Envía copia por correo de una notificación in-app. No lanza excepción
    si falla — el correo es un canal adicional, no debe romper el flujo principal."""
    dest = notificacion.idDestinatario
    if not dest or not dest.email:
        return
    asunto_tpl = TIPO_EVENTO_ASUNTO.get(notificacion.tipoEvento, 'Actualización de FUS — {folio}')
    asunto = asunto_tpl.format(folio=notificacion.fusFolio)
    try:
        send_mail(
            asunto,
            notificacion.mensaje,
            settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else settings.EMAIL_HOST_USER,
            [dest.email],
            fail_silently=True,
        )
    except Exception:
        logger.exception(f"No se pudo enviar correo de notificación a {dest.email}")
