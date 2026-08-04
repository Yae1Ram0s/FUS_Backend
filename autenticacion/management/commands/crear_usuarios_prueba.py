from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from autenticacion.models import CorreoAutorizado
from catalogos.models import UnidadAdministrativa


USUARIOS_PRUEBA = [
    ('prueba.rol1@anam.gob.mx', 'Prueba Rol 1', 'ROL1'),
    ('prueba.rol2@anam.gob.mx', 'Prueba Rol 2', 'ROL2'),
    ('prueba.comisionado@anam.gob.mx', 'Prueba Comisionado', 'COMISIONADO'),
    ('prueba.equipo@anam.gob.mx', 'Prueba Equipo Particular', 'EQUIPO_PARTICULAR'),
]


class Command(BaseCommand):
    help = 'Crea o actualiza usuarios locales de prueba para todos los roles.'

    def add_arguments(self, parser):
        parser.add_argument('--password', required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        password = options['password']
        if len(password) < 12:
            raise CommandError('La contraseña de prueba debe tener al menos 12 caracteres.')

        unidad = UnidadAdministrativa.objects.filter(activo=1).order_by(
            'idUnidadAdministrativa'
        ).first()
        if unidad is None:
            raise CommandError('No existen unidades administrativas activas.')

        rol1_autorizado = None
        for email, nombre, rol in USUARIOS_PRUEBA:
            autorizado, _ = CorreoAutorizado.objects.update_or_create(
                email=email,
                defaults={
                    'nombre': nombre,
                    'rol': rol,
                    'unidadAdministrativa': unidad if rol == 'COMISIONADO' else None,
                    'activo': 1,
                },
            )
            if rol == 'ROL1':
                rol1_autorizado = autorizado
            elif rol == 'EQUIPO_PARTICULAR' and rol1_autorizado:
                autorizado.idUsuarioRegistra = rol1_autorizado.id
                autorizado.save(update_fields=['idUsuarioRegistra'])

            usuario, _ = User.objects.update_or_create(
                username=email,
                defaults={
                    'email': email,
                    'first_name': nombre,
                    'is_active': True,
                },
            )
            usuario.set_password(password)
            usuario.save(update_fields=['password'])
            self.stdout.write(self.style.SUCCESS(f'{rol}: {email}'))
