"""Validación centralizada de códigos OTP — usada por verificar-otp,
establecer-contraseña y restablecer-contraseña, para no repetir (ni
desincronizar) la misma lógica de seguridad en cada vista.
"""
import secrets

from django.db import transaction
from django.utils import timezone

from .models import CodigoOTP

OTP_MAX_INTENTOS = 5
OTP_ERROR_GENERICO = 'Código incorrecto o expirado. Intenta de nuevo.'
OTP_ERROR_BLOQUEADO = 'Demasiados intentos fallidos. Solicita un nuevo código.'


def validar_otp(email, codigo, marcar_usado=False):
    """Valida el código OTP vigente de `email` contra `codigo`.

    - `select_for_update()` dentro de una transacción: si dos requests
      concurrentes intentan consumir el mismo OTP (doble clic, dos pestañas),
      la segunda espera a la primera en vez de leer un estado ya obsoleto.
    - Compara el código con `secrets.compare_digest` (tiempo constante, no
      revela por timing cuántos caracteres coinciden).
    - Un OTP usado, vencido o con `intentosFallidos >= OTP_MAX_INTENTOS`
      nunca se considera válido, sin importar que el código coincida.
    - Cada intento fallido incrementa `intentosFallidos` sobre el MISMO
      registro (nunca se generan intentos "sueltos" sin OTP detrás).
    - `marcar_usado=True` consume el OTP atómicamente junto con la
      validación (para los pasos que sí completan el flujo); en `False`
      solo valida, sin gastarlo (para el paso intermedio "verificar OTP").

    Devuelve (otp, None) si es válido, o (None, mensaje_error) si no.
    """
    with transaction.atomic():
        otp = (
            CodigoOTP.objects
            .select_for_update()
            .filter(email=email, usado=0)
            .order_by('-fechaGeneracion')
            .first()
        )

        if not otp:
            return None, OTP_ERROR_GENERICO
        if otp.fechaExpiracion <= timezone.now():
            return None, OTP_ERROR_GENERICO
        if otp.intentosFallidos >= OTP_MAX_INTENTOS:
            return None, OTP_ERROR_BLOQUEADO
        if not secrets.compare_digest(otp.codigo, codigo or ''):
            otp.intentosFallidos += 1
            otp.save(update_fields=['intentosFallidos'])
            if otp.intentosFallidos >= OTP_MAX_INTENTOS:
                return None, OTP_ERROR_BLOQUEADO
            return None, OTP_ERROR_GENERICO

        if marcar_usado:
            otp.usado = 1
            otp.save(update_fields=['usado'])

        return otp, None
