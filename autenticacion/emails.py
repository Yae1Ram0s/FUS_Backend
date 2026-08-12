import logging
import os
from email.mime.image import MIMEImage

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

_FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'frontend',
)
LOGO_SCS_PATH      = os.path.join(_FRONTEND_DIR, 'public', 'Logo SCS 2026_2.png')
LOGO_HACIENDA_PATH = os.path.join(_FRONTEND_DIR, 'src', 'assets', 'Logos_P_Hacienda_ANAM.png')
# Recorte de pleca.png reteñido a verde institucional muy tenue (10% alpha) y
# reducido a un tile — no es la imagen original, es una marca de agua
# generada para el fondo del correo. Ver README de esta carpeta / commit que
# la generó si hay que regenerarla desde un pleca.png distinto.
PLECA_WATERMARK_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'templates', 'autenticacion', 'emails', 'pleca_watermark.png'
)


def enviar_correo_otp(email, codigo, intro, asunto):
    """Envía el correo de código de verificación con el diseño institucional
    (tarjeta blanca, logos embebidos por CID, píldora verde con el código).
    fail_silently=False — igual que el send_mail que reemplaza, los tres
    call sites (correo nuevo/reenvío/recuperación) dependen de que el error
    se propague si el correo no pudo enviarse."""
    html_body = render_to_string('autenticacion/emails/otp.html', {
        'intro': intro,
        'codigo': codigo,
    })
    texto_plano = (
        f'Estimado/a usuario/a:\n\n{intro}\n\n'
        f'Código de verificación: {codigo}\n\n'
        f'Válido por 15 minutos. Uso único.\n\n'
        f'Si no has solicitado este código, ignora este correo o contacta a soporte técnico.'
    )

    remitente = getattr(settings, 'DEFAULT_FROM_EMAIL', settings.EMAIL_HOST_USER)
    msg = EmailMultiAlternatives(asunto, texto_plano, remitente, [email])
    msg.attach_alternative(html_body, 'text/html')

    imagenes = (
        ('logo_scs', LOGO_SCS_PATH),
        ('logo_hacienda', LOGO_HACIENDA_PATH),
        ('pleca_watermark', PLECA_WATERMARK_PATH),
    )
    for cid, ruta in imagenes:
        try:
            with open(ruta, 'rb') as f:
                img = MIMEImage(f.read())
            img.add_header('Content-ID', f'<{cid}>')
            img.add_header('Content-Disposition', 'inline', filename=os.path.basename(ruta))
            msg.attach(img)
        except OSError:
            logger.warning(f'No se encontró el logo para el correo OTP: {ruta}')

    # El administrador puede auditar el resultado del proveedor sin acceder
    # jamás al código. Los OTP históricos permanecen SIN_CONFIRMACION.
    from .models import CodigoOTP
    otp = CodigoOTP.objects.filter(email__iexact=email, codigo=codigo).order_by('-id').first()
    try:
        enviados = msg.send(fail_silently=False)
        if otp:
            otp.estadoEnvio = 'ENVIADO' if enviados else 'ERROR'
            otp.fechaEnvio = timezone.now() if enviados else None
            otp.detalleEnvio = '' if enviados else 'El proveedor no confirmó destinatarios.'
            otp.save(update_fields=['estadoEnvio', 'fechaEnvio', 'detalleEnvio'])
        return enviados
    except Exception as exc:
        if otp:
            otp.estadoEnvio = 'ERROR'
            otp.fechaEnvio = None
            # Solo se conserva el tipo del error; evita credenciales, tokens o
            # respuestas completas del proveedor en la base de datos.
            otp.detalleEnvio = f'Error de correo: {exc.__class__.__name__}'[:160]
            otp.save(update_fields=['estadoEnvio', 'fechaEnvio', 'detalleEnvio'])
        raise
