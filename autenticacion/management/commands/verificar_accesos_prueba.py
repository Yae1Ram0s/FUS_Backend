from django.core.management.base import BaseCommand, CommandError
from rest_framework.test import APIClient


CASOS = [
    ('prueba.rol1@anam.gob.mx', '/api/fus/'),
    ('prueba.rol2@anam.gob.mx', '/api/turnados/mis-turnados/'),
    ('prueba.comisionado@anam.gob.mx', '/api/fus/mis-comisionados/'),
    ('prueba.equipo@anam.gob.mx', '/api/fus/'),
]


class Command(BaseCommand):
    help = 'Comprueba login JWT y acceso principal de cada usuario de prueba.'

    def add_arguments(self, parser):
        parser.add_argument('--password', required=True)

    def handle(self, *args, **options):
        for email, endpoint in CASOS:
            cliente = APIClient()
            verificacion = cliente.post(
                '/api/auth/verificar-correo/',
                {'email': email},
                format='json',
                HTTP_HOST='localhost',
            )
            if verificacion.status_code != 200:
                raise CommandError(
                    f'Verificación falló para {email}: HTTP {verificacion.status_code}'
                )

            login = cliente.post(
                '/api/auth/login/',
                {'email': email, 'password': options['password']},
                format='json',
                HTTP_HOST='localhost',
            )
            if login.status_code != 200:
                raise CommandError(f'Login falló para {email}: HTTP {login.status_code}')

            token = login.data.get('access')
            cliente.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
            respuesta = cliente.get(endpoint, HTTP_HOST='localhost')
            if respuesta.status_code != 200:
                raise CommandError(
                    f'Acceso falló para {email} en {endpoint}: HTTP {respuesta.status_code}'
                )
            self.stdout.write(
                self.style.SUCCESS(f'{email}: login y {endpoint} OK')
            )
