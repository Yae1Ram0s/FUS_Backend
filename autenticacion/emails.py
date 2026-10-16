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


def enviar_correo_otp_rapido(email, codigo, intro, asunto, espera=2.5):
    """Igual que `enviar_correo_otp`, pero sin dejar la respuesta HTTP
    esperando a que el servidor de correo conteste.

    El envío corre en un hilo aparte y la petición espera como máximo
    `espera` segundos: si en ese lapso el envío ya terminó, el resultado (o el
    error) se comporta exactamente como antes; si el SMTP está lento, la
    respuesta sale de inmediato y el envío termina en segundo plano — su
    resultado queda en `CodigoOTP.estadoEnvio`, que el administrador ya puede
    auditar. Sin esto, un SMTP lento dejaba el botón del login "Verificando…"
    hasta EMAIL_TIMEOUT (10 s) en el primer ingreso, y se leía como trabado.

    Devuelve lo mismo que `enviar_correo_otp`, o None si el envío sigue en
    curso al responder."""
    import threading

    from django.db import connections

    resultado = {}

    def _tarea():
        try:
            resultado['enviados'] = enviar_correo_otp(email, codigo, intro, asunto)
        except Exception as exc:  # se re-lanza en el hilo del request si ya terminó
            resultado['error'] = exc
        finally:
            # Un hilo aparte no pasa por el cierre automático de conexiones de
            # Django (fin de request): sin esto queda una conexión huérfana.
            connections.close_all()

    hilo = threading.Thread(target=_tarea, daemon=True)
    hilo.start()
    hilo.join(timeout=espera)
    if 'error' in resultado:
        raise resultado['error']
    return resultado.get('enviados')
