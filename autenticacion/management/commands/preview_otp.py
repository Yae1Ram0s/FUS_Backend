import base64
import tempfile
import webbrowser
import os

from django.core.management.base import BaseCommand
from django.template.loader import render_to_string

from autenticacion.emails import LOGO_SCS_PATH, LOGO_HACIENDA_PATH, PLECA_WATERMARK_PATH


class Command(BaseCommand):
    help = 'Renderiza el correo de código OTP con datos de ejemplo y lo abre en el navegador.'

    def add_arguments(self, parser):
        parser.add_argument('--codigo', default='123450')
        parser.add_argument(
            '--intro',
            default='Recibimos una solicitud de acceso al Sistema de Control de Solicitudes. '
                    'Utiliza el siguiente código para completar tu inicio de sesión.',
        )

    def handle(self, *args, **options):
        html = render_to_string('autenticacion/emails/otp.html', {
            'intro': options['intro'],
            'codigo': options['codigo'],
        })

        # El navegador no resuelve cid:, así que para la vista previa se
        # incrustan las mismas imágenes que el correo real como base64.
        for cid, ruta in (
            ('logo_scs', LOGO_SCS_PATH),
            ('logo_hacienda', LOGO_HACIENDA_PATH),
            ('pleca_watermark', PLECA_WATERMARK_PATH),
        ):
            with open(ruta, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode()
            html = html.replace(f'cid:{cid}', f'data:image/png;base64,{b64}')

        fd, ruta_html = tempfile.mkstemp(suffix='.html', prefix='preview_otp_')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(html)

        webbrowser.open(f'file://{ruta_html}')
        self.stdout.write(self.style.SUCCESS(f'Vista previa abierta: {ruta_html}'))
