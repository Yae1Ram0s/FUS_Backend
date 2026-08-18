"""Genera un par de llaves VAPID nuevo para Web Push (ver backend/settings.py
y services/notificaciones.py) — cada ambiente (dev, staging, producción)
debe tener su propio par, nunca reutilizar el de otro.

Ejecutar y copiar el resultado a las variables de entorno VAPID_PUBLIC_KEY /
VAPID_PRIVATE_KEY del ambiente correspondiente:

    python manage.py generar_vapid_keys
"""
import base64

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.core.management.base import BaseCommand
from py_vapid import Vapid02


class Command(BaseCommand):
    help = 'Genera un par de llaves VAPID nuevo para Web Push.'

    def handle(self, *args, **options):
        vapid = Vapid02()
        vapid.generate_keys()

        priv_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, 'big')
        priv_b64 = base64.urlsafe_b64encode(priv_raw).rstrip(b'=').decode()

        pub_bytes = vapid.public_key.public_bytes(
            encoding=Encoding.X962, format=PublicFormat.UncompressedPoint,
        )
        pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()

        self.stdout.write(self.style.SUCCESS('Par VAPID generado — agrégalo a las variables de entorno de este ambiente:'))
        self.stdout.write(f'VAPID_PUBLIC_KEY={pub_b64}')
        self.stdout.write(f'VAPID_PRIVATE_KEY={priv_b64}')
