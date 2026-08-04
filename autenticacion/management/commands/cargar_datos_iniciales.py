from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from autenticacion.models import CorreoAutorizado
from catalogos.models import UnidadAdministrativa


UNIDADES = [
    (1, 'OF-TIT', 'Oficina del Titular'),
    (2, 'UAF', 'Unidad de Administración y Finanzas'),
    (3, 'ANL', 'Aduana de Nuevo Laredo'),
    (4, 'AMAN', 'Aduana de Manzanillo'),
    (5, 'AICM', 'Aduana del Aeropuerto Internacional de la Ciudad de México'),
    (6, 'AVER', 'Aduana de Veracruz'),
]

# email, nombre, rol, unidad, email del ROL1 asociado
USUARIOS = [
    ('anabel.munoz@anam.gob.mx', 'Anabel Muñoz Trejo', 'ROL1', 1, None),
    ('mariana.lopez@anam.gob.mx', 'Mariana López Aguilar', 'EQUIPO_PARTICULAR', 1, 'anabel.munoz@anam.gob.mx'),
    ('fernando.ruiz@anam.gob.mx', 'Fernando Ruiz Salgado', 'EQUIPO_PARTICULAR', 1, 'anabel.munoz@anam.gob.mx'),

    ('luis.cardenas@anam.gob.mx', 'Luis Cárdenas Ortega', 'ROL2', 2, None),
    ('claudia.morales@anam.gob.mx', 'Claudia Morales Vega', 'COMISIONADO', 2, None),
    ('eduardo.sanchez@anam.gob.mx', 'Eduardo Sánchez Luna', 'COMISIONADO', 2, None),

    ('adriana.torres@anam.gob.mx', 'Adriana Torres Navarro', 'ROL2', 3, None),
    ('gabriela.flores@anam.gob.mx', 'Gabriela Flores Ríos', 'COMISIONADO', 3, None),
    ('oscar.martinez@anam.gob.mx', 'Óscar Martínez Pineda', 'COMISIONADO', 3, None),

    ('ricardo.mendoza@anam.gob.mx', 'Ricardo Mendoza Castillo', 'ROL2', 4, None),
    ('patricia.romero@anam.gob.mx', 'Patricia Romero Díaz', 'COMISIONADO', 4, None),
    ('hector.vargas@anam.gob.mx', 'Héctor Vargas Medina', 'COMISIONADO', 4, None),

    ('paola.herrera@anam.gob.mx', 'Paola Herrera Campos', 'ROL2', 5, None),
    ('monica.guzman@anam.gob.mx', 'Mónica Guzmán Reyes', 'COMISIONADO', 5, None),
    ('daniel.castro@anam.gob.mx', 'Daniel Castro Silva', 'COMISIONADO', 5, None),

    ('jorge.ramirez@anam.gob.mx', 'Jorge Ramírez Fuentes', 'ROL2', 6, None),
    ('alejandra.ortiz@anam.gob.mx', 'Alejandra Ortiz Cabrera', 'COMISIONADO', 6, None),
    ('manuel.jimenez@anam.gob.mx', 'Manuel Jiménez Soto', 'COMISIONADO', 6, None),
]


class Command(BaseCommand):
    help = 'Carga unidades y usuarios iniciales de prueba sin duplicar registros.'

    def add_arguments(self, parser):
        parser.add_argument('--password', required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        password = options['password']
        if len(password) < 12:
            raise CommandError('La contraseña inicial debe tener al menos 12 caracteres.')

        for identificador, clave, nombre in UNIDADES:
            UnidadAdministrativa.objects.update_or_create(
                idUnidadAdministrativa=identificador,
                defaults={
                    'clave': clave,
                    'unidadAdministrativa': nombre,
                    'esUnidadAdministrativa': 1,
                    'esUnidadDeNegocio': 0,
                    'activo': 1,
                },
            )

        autorizados = {}
        for email, nombre, rol, unidad_id, _ in USUARIOS:
            autorizado, _ = CorreoAutorizado.objects.update_or_create(
                email=email,
                defaults={
                    'nombre': nombre,
                    'rol': rol,
                    'unidadAdministrativa_id': unidad_id,
                    'activo': 1,
                },
            )
            autorizados[email] = autorizado

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

        for email, _, rol, _, rol1_email in USUARIOS:
            if rol != 'EQUIPO_PARTICULAR' or not rol1_email:
                continue
            autorizado = autorizados[email]
            autorizado.idUsuarioRegistra = autorizados[rol1_email].id
            autorizado.save(update_fields=['idUsuarioRegistra'])

        self.stdout.write(
            self.style.SUCCESS(
                f'Carga inicial completa: {len(UNIDADES)} unidades y '
                f'{len(USUARIOS)} usuarios.'
            )
        )
