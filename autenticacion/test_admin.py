from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APITestCase
from autenticacion.admin_services import emitir_tokens
from autenticacion.models import AuditoriaAdministrativa, CodigoOTP, CorreoAutorizado, SeguridadUsuario
from django.utils import timezone
from datetime import timedelta
from catalogos.models import UnidadAdministrativa


class AdminAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('admin@test.mx', 'admin@test.mx', 'Admin2026!Seguro')
        cls.normal = User.objects.create_user('normal@test.mx', 'normal@test.mx', 'Normal2026!Seguro')
        CorreoAutorizado.objects.create(email=cls.admin.email, nombre='Admin', rol='ADMIN', activo=1)
        CorreoAutorizado.objects.create(email=cls.normal.email, nombre='Normal', rol='ROL2', activo=1)

    def auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {emitir_tokens(user).access_token}')

    def test_solo_admin(self):
        self.auth(self.normal)
        self.assertEqual(self.client.get('/api/auth/admin/resumen/').status_code, 403)
        self.auth(self.admin)
        self.assertEqual(self.client.get('/api/auth/admin/resumen/').status_code, 200)

    def test_listado_no_expone_hash_y_filtra(self):
        self.auth(self.admin)
        response = self.client.get('/api/auth/admin/usuarios/?rol=ROL2&tiene_contrasena=true')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        serialized = str(response.data).lower()
        self.assertNotIn('password', serialized)
        self.assertNotIn('hash', serialized)

    def test_listado_serializa_unidad_con_clave_primaria_personalizada(self):
        unidad = UnidadAdministrativa(
            idUnidadAdministrativa=91,
            clave='QA-ADMIN',
            unidadAdministrativa='Unidad de prueba administrativa',
            activo=1,
        )
        # El catálogo es legacy/managed=False; se persiste explícitamente en
        # la BD temporal para reproducir la estructura usada en producción.
        unidad.save(force_insert=True)
        autorizado = CorreoAutorizado.objects.get(email=self.normal.email)
        autorizado.unidadAdministrativa = unidad
        autorizado.save(update_fields=['unidadAdministrativa'])
        self.auth(self.admin)
        response = self.client.get('/api/auth/admin/usuarios/')
        self.assertEqual(response.status_code, 200)
        usuario = next(item for item in response.data['results'] if item['email'] == self.normal.email)
        self.assertEqual(usuario['unidadAdministrativa']['id'], 91)

    def test_restaurar_temporal_revoca_token_y_audita(self):
        old = str(emitir_tokens(self.normal).access_token)
        self.auth(self.admin)
        response = self.client.post(f'/api/auth/admin/usuarios/{self.normal.id}/restablecer-contrasena/', {'metodo': 'temporal'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('passwordTemporal', response.data)
        self.assertTrue(SeguridadUsuario.objects.get(usuario=self.normal).requiereCambioContrasena)
        self.assertTrue(AuditoriaAdministrativa.objects.filter(objetivo=self.normal).exists())
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {old}')
        self.assertEqual(self.client.get('/api/auth/admin/resumen/').status_code, 401)

    def test_no_desactiva_ultimo_admin_ni_propia_cuenta(self):
        self.auth(self.admin)
        response = self.client.post(f'/api/auth/admin/usuarios/{self.admin.id}/desactivar/')
        self.assertIn(response.status_code, (400, 409))

    def test_admin_elimina_usuario_sin_relaciones(self):
        descartable = User.objects.create_user('descartable@test.mx', 'descartable@test.mx', 'Temporal2026!')
        CorreoAutorizado.objects.create(email=descartable.email, nombre='Descartable', rol='COMISIONADO', activo=1)
        self.auth(self.admin)
        response = self.client.delete(f'/api/auth/admin/usuarios/{descartable.id}/')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(email=descartable.email).exists())
        self.assertFalse(CorreoAutorizado.objects.filter(email=descartable.email).exists())

    def test_admin_no_puede_eliminarse_a_si_mismo(self):
        self.auth(self.admin)
        response = self.client.delete(f'/api/auth/admin/usuarios/{self.admin.id}/')
        self.assertEqual(response.status_code, 400)

    def test_admin_da_de_alta_correo_operativo(self):
        self.auth(self.admin)
        response = self.client.post('/api/auth/admin/usuarios/', {
            'email': 'nuevo.usuario@anam.gob.mx', 'nombre': 'Nuevo Usuario', 'rol': 'ROL2'
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(CorreoAutorizado.objects.filter(email='nuevo.usuario@anam.gob.mx', rol='ROL2').exists())
        self.assertFalse(User.objects.filter(email='nuevo.usuario@anam.gob.mx').exists())

    def test_alta_admin_no_permite_crear_otro_admin(self):
        self.auth(self.admin)
        response = self.client.post('/api/auth/admin/usuarios/', {
            'email': 'otro.admin@anam.gob.mx', 'nombre': 'Otro Admin', 'rol': 'ADMIN'
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_salud_sin_secretos(self):
        self.auth(self.admin)
        response = self.client.get('/api/auth/admin/salud/')
        self.assertEqual(response.status_code, 200)
        body = str(response.data).lower()
        for secret in ('secret_key', 'password', 'database_url', 'email_host_password'):
            self.assertNotIn(secret, body)

    def test_salud_explica_advertencia_websocket_en_memoria(self):
        self.auth(self.admin)
        response = self.client.get('/api/auth/admin/salud/?forzar=true')
        self.assertEqual(response.status_code, 200)
        websocket = response.data['websocket']
        if websocket['backend'] == 'InMemoryChannelLayer':
            self.assertFalse(websocket['configurado'])
            self.assertEqual(websocket['codigo'], 'WS_MEMORIA_LOCAL')
            self.assertIn('diagnostico', websocket)
            self.assertIn('impacto', websocket)
            self.assertIn('recomendacion', websocket)
            self.assertGreater(len(websocket['comprobaciones']), 0)

    def test_metricas_admin_reconcilian_y_no_exponen_secretos(self):
        self.auth(self.admin)
        response = self.client.get('/api/auth/admin/metricas/?dias=30')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['kpis']['usuariosAutorizados'], 2)
        self.assertEqual(len(response.data['serie']), 30)
        self.assertIn('latenciaBaseDatosMs', response.data['red'])
        self.assertIn('sesionesVigentes', response.data['red'])
        serialized = str(response.data).lower()
        self.assertNotIn('password', serialized)
        self.assertNotIn('token', serialized)

    def test_login_temporal_exige_cambio(self):
        sec, _ = SeguridadUsuario.objects.get_or_create(usuario=self.admin)
        sec.requiereCambioContrasena = True; sec.save()
        self.client.credentials()
        response = self.client.post('/api/auth/login/', {'email': self.admin.email, 'password': 'Admin2026!Seguro'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['user']['requiereCambioContrasena'])

    def test_usuario_cambia_contrasena_temporal_antes_de_entrar(self):
        sec, _ = SeguridadUsuario.objects.get_or_create(usuario=self.admin)
        sec.requiereCambioContrasena = True
        sec.save()
        self.client.credentials()
        login = self.client.post('/api/auth/login/', {
            'email': self.admin.email,
            'password': 'Admin2026!Seguro',
        }, format='json')
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        bloqueado = self.client.get('/api/auth/admin/resumen/')
        self.assertEqual(bloqueado.status_code, 401)
        response = self.client.post('/api/auth/cambiar-contrasena-obligatoria/', {
            'passwordActual': 'Admin2026!Seguro',
            'passwordNueva': 'Nueva2026!Segura',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['requiereCambioContrasena'])
        self.assertIn('access', response.data)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('Nueva2026!Segura'))
        self.assertFalse(SeguridadUsuario.objects.get(usuario=self.admin).requiereCambioContrasena)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        permitido = self.client.get('/api/auth/admin/resumen/')
        self.assertEqual(permitido.status_code, 200)

    def test_supervision_otp_no_expone_codigo(self):
        CodigoOTP.objects.create(
            email='nuevo@anam.gob.mx', codigo='654321',
            fechaExpiracion=timezone.now() + timedelta(minutes=15),
            estadoEnvio='ENVIADO', fechaEnvio=timezone.now(),
        )
        self.auth(self.admin)
        response = self.client.get('/api/auth/admin/otp/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'][0]['estadoEnvio'], 'ENVIADO')
        self.assertNotIn('654321', str(response.data))
        self.assertNotIn('codigo', str(response.data).lower())


class AdminCommandTests(APITestCase):
    def test_comando_es_idempotente(self):
        call_command('crear_administrador_sistema')
        call_command('crear_administrador_sistema')
        self.assertEqual(CorreoAutorizado.objects.filter(email='admin@anam.gob.mx', rol='ADMIN').count(), 1)
        user = User.objects.get(email='admin@anam.gob.mx')
        self.assertTrue(user.check_password('Anam2026!admi'))
        self.assertTrue(SeguridadUsuario.objects.get(usuario=user).requiereCambioContrasena)
