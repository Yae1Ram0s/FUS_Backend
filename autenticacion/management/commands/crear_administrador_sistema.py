from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from autenticacion.admin_services import restablecer_temporal
from autenticacion.models import CorreoAutorizado, SeguridadUsuario


class Command(BaseCommand):
    help = 'Crea o normaliza idempotentemente el administrador inicial del SCS.'

    def add_arguments(self, parser):
        parser.add_argument('--email', default='admin@anam.gob.mx')
        parser.add_argument('--password', default='Anam2026!admi')
        parser.add_argument('--nombre', default='Administrador del sistema')
        parser.add_argument('--reset-password', action='store_true', help='También restablece la contraseña si la cuenta ya existía.')

    @transaction.atomic
    def handle(self, *args, **opts):
        email = opts['email'].strip().lower()
        autorizado, _ = CorreoAutorizado.objects.update_or_create(email=email, defaults={'nombre': opts['nombre'], 'rol': 'ADMIN', 'activo': 1})
        user, created = User.objects.get_or_create(username=email, defaults={'email': email, 'first_name': opts['nombre'], 'is_active': True})
        changed = []
        if user.email != email: user.email = email; changed.append('email')
        if not user.is_active: user.is_active = True; changed.append('is_active')
        if changed: user.save(update_fields=changed)
        if created or not user.has_usable_password() or opts['reset_password']:
            restablecer_temporal(user, opts['password'])
            self.stdout.write(self.style.WARNING(f'Contraseña temporal establecida para {email}; debe cambiarse en el primer acceso.'))
        else:
            SeguridadUsuario.objects.get_or_create(usuario=user)
        self.stdout.write(self.style.SUCCESS(f'Administrador listo: {email}'))
