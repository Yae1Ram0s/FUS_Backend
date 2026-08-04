import threading
from datetime import timedelta

from django import db
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import CorreoAutorizado, CodigoOTP
from .otp import validar_otp, OTP_MAX_INTENTOS


class ValidarOTPTests(TestCase):
    """Pruebas unitarias directas sobre autenticacion.otp.validar_otp —
    la función centralizada que usan verificar-otp, establecer-contraseña y
    restablecer-contraseña."""

    def setUp(self):
        self.email = 'otp-test@anam.gob.mx'

    def _crear_otp(self, codigo='123456', minutos_vigencia=15, usado=0, intentos=0):
        return CodigoOTP.objects.create(
            email=self.email, codigo=codigo,
            fechaExpiracion=timezone.now() + timedelta(minutes=minutos_vigencia),
            usado=usado, intentosFallidos=intentos,
        )

    def test_codigo_correcto_es_valido(self):
        self._crear_otp(codigo='111111')
        otp, error = validar_otp(self.email, '111111', marcar_usado=False)
        self.assertIsNone(error)
        self.assertIsNotNone(otp)

    def test_codigo_incorrecto_es_invalido(self):
        self._crear_otp(codigo='111111')
        otp, error = validar_otp(self.email, '999999', marcar_usado=False)
        self.assertIsNone(otp)
        self.assertIsNotNone(error)

    def test_codigo_incorrecto_incrementa_intentos_fallidos(self):
        otp = self._crear_otp(codigo='111111')
        validar_otp(self.email, '999999', marcar_usado=False)
        otp.refresh_from_db()
        self.assertEqual(otp.intentosFallidos, 1)

    def test_se_bloquea_al_quinto_intento_fallido(self):
        self._crear_otp(codigo='111111')
        for _ in range(OTP_MAX_INTENTOS - 1):
            _, error = validar_otp(self.email, '000000', marcar_usado=False)
            self.assertEqual(error, 'Código incorrecto o expirado. Intenta de nuevo.')
        # Quinto fallo: ya debe reportar bloqueo, no el mensaje genérico.
        _, error = validar_otp(self.email, '000000', marcar_usado=False)
        self.assertEqual(error, 'Demasiados intentos fallidos. Solicita un nuevo código.')

    def test_bloqueado_rechaza_incluso_el_codigo_correcto(self):
        otp = self._crear_otp(codigo='111111', intentos=OTP_MAX_INTENTOS)
        _, error = validar_otp(self.email, '111111', marcar_usado=False)
        self.assertEqual(error, 'Demasiados intentos fallidos. Solicita un nuevo código.')

    def test_otp_usado_es_invalido(self):
        self._crear_otp(codigo='111111', usado=1)
        _, error = validar_otp(self.email, '111111', marcar_usado=False)
        self.assertIsNotNone(error)

    def test_otp_vencido_es_invalido(self):
        self._crear_otp(codigo='111111', minutos_vigencia=-1)
        _, error = validar_otp(self.email, '111111', marcar_usado=False)
        self.assertIsNotNone(error)

    def test_sin_otp_generado_es_invalido(self):
        _, error = validar_otp(self.email, '111111', marcar_usado=False)
        self.assertIsNotNone(error)

    def test_marcar_usado_consume_el_otp(self):
        otp = self._crear_otp(codigo='111111')
        validar_otp(self.email, '111111', marcar_usado=True)
        otp.refresh_from_db()
        self.assertEqual(otp.usado, 1)

    def test_no_se_puede_reutilizar_un_otp_ya_consumido(self):
        self._crear_otp(codigo='111111')
        _, error1 = validar_otp(self.email, '111111', marcar_usado=True)
        self.assertIsNone(error1)
        _, error2 = validar_otp(self.email, '111111', marcar_usado=True)
        self.assertIsNotNone(error2)

class ValidarOTPConcurrenciaTests(TransactionTestCase):
    """Igual que los de arriba pero con TransactionTestCase: TestCase envuelve
    cada prueba en una transacción que nunca se confirma, así que una
    conexión aparte (otro hilo) no vería la fila creada por setUp() y la
    prueba de carrera sería un falso positivo sin sentido. TransactionTestCase
    sí confirma de verdad entre operaciones, como en producción."""

    def setUp(self):
        self.email = 'otp-concurrencia@anam.gob.mx'

    def _crear_otp(self, codigo='777777', minutos_vigencia=15):
        return CodigoOTP.objects.create(
            email=self.email, codigo=codigo,
            fechaExpiracion=timezone.now() + timedelta(minutes=minutos_vigencia),
        )

    def test_consumo_concurrente_solo_deja_pasar_a_uno(self):
        """Dos hilos con conexiones de BD reales intentando consumir el mismo
        OTP al mismo tiempo — select_for_update() debe garantizar que solo
        uno gane la carrera."""
        self._crear_otp(codigo='777777')
        resultados = []

        def intentar():
            db.connections.close_all()
            _, error = validar_otp(self.email, '777777', marcar_usado=True)
            resultados.append(error)
            db.connections.close_all()

        hilos = [threading.Thread(target=intentar) for _ in range(2)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        exitosos = resultados.count(None)
        self.assertEqual(exitosos, 1, f'se esperaba exactamente 1 consumo exitoso, hubo {exitosos}: {resultados}')


class OTPFlowAPITests(APITestCase):
    """Extremo a extremo sobre los endpoints reales que usan validar_otp."""

    @classmethod
    def setUpTestData(cls):
        cls.email = 'nuevo@anam.gob.mx'
        CorreoAutorizado.objects.create(email=cls.email, nombre='Nuevo Usuario', rol='ROL1', activo=1)

    def setUp(self):
        # OTPThrottle cuenta por IP en el cache — sin esto, varias pruebas de
        # esta clase corriendo seguidas agotan el límite ('otp': 5/minuto) y
        # empiezan a fallar con 429 en vez del status que cada una espera.
        cache.clear()

    def _crear_otp(self, codigo='123456', minutos_vigencia=15, usado=0, intentos=0):
        return CodigoOTP.objects.create(
            email=self.email, codigo=codigo,
            fechaExpiracion=timezone.now() + timedelta(minutes=minutos_vigencia),
            usado=usado, intentosFallidos=intentos,
        )

    def test_verificar_otp_no_consume_el_codigo(self):
        self._crear_otp(codigo='555555')
        resp = self.client.post('/api/auth/verificar-otp/', {'email': self.email, 'codigo': '555555'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Sigue sin usarse — establecer-contraseña debe poder consumirlo después.
        otp = CodigoOTP.objects.get(email=self.email, codigo='555555')
        self.assertEqual(otp.usado, 0)

    def test_verificar_otp_incorrecto_400(self):
        self._crear_otp(codigo='555555')
        resp = self.client.post('/api/auth/verificar-otp/', {'email': self.email, 'codigo': '000000'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_establecer_contrasena_crea_usuario_y_consume_otp(self):
        self._crear_otp(codigo='555555')
        resp = self.client.post('/api/auth/establecer-contrasena/', {
            'email': self.email, 'codigo': '555555', 'password': 'Sup3rSegura!2026',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(User.objects.filter(email=self.email).exists())
        otp = CodigoOTP.objects.get(email=self.email, codigo='555555')
        self.assertEqual(otp.usado, 1)

    def test_establecer_contrasena_con_otp_bloqueado_400(self):
        self._crear_otp(codigo='555555', intentos=OTP_MAX_INTENTOS)
        resp = self.client.post('/api/auth/establecer-contrasena/', {
            'email': self.email, 'codigo': '555555', 'password': 'Sup3rSegura!2026',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email=self.email).exists())

    def test_restablecer_contrasena_consume_otp_y_cambia_password(self):
        user = User.objects.create_user(username=self.email, email=self.email, password='ViejaPass!123')
        self._crear_otp(codigo='555555')
        resp = self.client.post('/api/auth/restablecer-contrasena/', {
            'email': self.email, 'codigo': '555555', 'password': 'NuevaPass!2026',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.check_password('NuevaPass!2026'))
        otp = CodigoOTP.objects.get(email=self.email, codigo='555555')
        self.assertEqual(otp.usado, 1)

    def test_restablecer_contrasena_con_otp_vencido_400(self):
        User.objects.create_user(username=self.email, email=self.email, password='ViejaPass!123')
        self._crear_otp(codigo='555555', minutos_vigencia=-1)
        resp = self.client.post('/api/auth/restablecer-contrasena/', {
            'email': self.email, 'codigo': '555555', 'password': 'NuevaPass!2026',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
