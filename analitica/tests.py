import io
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.test import APITestCase

from autenticacion.models import CorreoAutorizado

from .models import EventoUso


class AnaliticaAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('admin-analitica@test.mx', 'admin-analitica@test.mx', 'Admin2026!')
        cls.usuario = User.objects.create_user('usuario-analitica@test.mx', 'usuario-analitica@test.mx', 'Usuario2026!')
        cls.otro = User.objects.create_user('otro-analitica@test.mx', 'otro-analitica@test.mx', 'Otro2026!')
        CorreoAutorizado.objects.create(email=cls.admin.email, nombre='Admin', rol='ADMIN', activo=1)
        CorreoAutorizado.objects.create(email=cls.usuario.email, nombre='Usuario', rol='ROL2', activo=1)
        CorreoAutorizado.objects.create(email=cls.otro.email, nombre='Otro', rol='COMISIONADO', activo=1)

    def payload(self, **overrides):
        base = {
            'idEvento': str(uuid.uuid4()),
            'ocurridoEn': timezone.now().isoformat(),
            'sesionId': 'sesion_analitica_001',
            'modulo': 'REPORTES',
            'componente': 'BOTON_EXPORTAR',
            'evento': 'INTERACTION',
            'accion': 'EXPORT',
            'resultado': 'RECORDED',
            'ruta': '/rol2/reportes',
            'duracionMs': 350,
            'dispositivo': 'ESCRITORIO',
            'viewportWidth': 1440,
            'appVersion': '1.0.0',
            'metadatos': {'formato': 'xlsx', 'total': 3},
        }
        base.update(overrides)
        return base

    def post(self, user, data):
        self.client.force_authenticate(user)
        return self.client.post('/api/analitica/eventos/', data, format='json')

    def test_ingesta_requiere_autenticacion_y_resumen_solo_admin(self):
        self.assertEqual(self.client.post('/api/analitica/eventos/', self.payload(), format='json').status_code, 401)
        self.client.force_authenticate(self.usuario)
        self.assertEqual(self.client.get('/api/analitica/admin/resumen/').status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get('/api/analitica/admin/resumen/').status_code, 200)

    def test_wrapper_lote_snapshot_servidor_y_campos_cliente_no_son_confiables(self):
        payload = self.payload()
        payload.update({'rolSnapshot': 'ADMIN', 'unidadSnapshot': 'Falsa', 'usuario': self.admin.id})
        response = self.post(self.usuario, {'eventos': [payload]})
        self.assertEqual(response.status_code, 201)
        evento = EventoUso.objects.get()
        self.assertEqual(evento.usuario, self.usuario)
        self.assertEqual(evento.rolSnapshot, 'ROL2')
        self.assertEqual(evento.unidadSnapshot, '')

    def test_uuid_deduplica_reintentos_y_repetidos_en_lote(self):
        payload = self.payload()
        primero = self.post(self.usuario, {'eventos': [payload, payload]})
        segundo = self.post(self.usuario, payload)
        self.assertEqual(primero.status_code, 201)
        self.assertEqual(primero.data['creados'], 1)
        self.assertEqual(primero.data['duplicados'], 1)
        self.assertEqual(segundo.data['creados'], 0)
        self.assertEqual(segundo.data['duplicados'], 1)
        self.assertEqual(EventoUso.objects.count(), 1)

    def test_rechaza_pii_taxonomia_y_lotes_mayores_al_limite(self):
        con_pii = self.post(self.usuario, self.payload(metadatos={'correo': 'persona@anam.gob.mx'}))
        self.assertEqual(con_pii.status_code, 400)
        taxonomia = self.post(self.usuario, self.payload(modulo='MODULO_INVENTADO'))
        self.assertEqual(taxonomia.status_code, 400)
        lote = self.post(self.usuario, {'eventos': [self.payload() for _ in range(51)]})
        self.assertEqual(lote.status_code, 400)
        self.assertEqual(EventoUso.objects.count(), 0)

    def test_ruta_no_admite_query_ni_identificadores(self):
        response = self.post(self.usuario, self.payload(ruta='/rol1/consultar-fus/12345?token=secreto'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(EventoUso.objects.count(), 0)

    def test_resumen_filtra_y_reconcilia_totales(self):
        eventos = [
            self.payload(
                modulo='REPORTES', evento='TASK_STARTED', accion='EXPORT', resultado='STARTED',
                sesionId='sesion_reportes_001', dispositivo='ESCRITORIO',
            ),
            self.payload(
                modulo='REPORTES', evento='TASK_COMPLETED', accion='EXPORT', resultado='COMPLETED',
                sesionId='sesion_reportes_001', dispositivo='ESCRITORIO', duracionMs=1000,
            ),
            self.payload(
                modulo='CALENDARIO', componente='CALENDARIO_MES', evento='PAGE_VIEW', accion='NAVIGATE',
                resultado='COMPLETED', sesionId='sesion_calendario_001', dispositivo='MOVIL', viewportWidth=390,
                ruta='/rol2/calendario',
            ),
        ]
        self.assertEqual(self.post(self.usuario, {'eventos': eventos}).status_code, 201)
        self.assertEqual(self.post(self.otro, self.payload(
            modulo='CALENDARIO', componente='BOTON_NUEVO', accion='CREATE',
            sesionId='sesion_otro_001', dispositivo='TABLETA', viewportWidth=900,
            ruta='/comisionado/calendario',
        )).status_code, 201)

        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/analitica/admin/resumen/?dias=7&rol=ROL2&modulo=REPORTES')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['cobertura']['eventos'], 2)
        self.assertEqual(response.data['kpis']['usuariosActivos'], 1)
        self.assertEqual(response.data['kpis']['modulosUsados'], 1)
        self.assertEqual(sum(row['eventos'] for row in response.data['serie']), 2)
        self.assertEqual(sum(row['eventos'] for row in response.data['modulos']), 2)
        self.assertEqual(response.data['kpis']['tasaExito'], 100.0)
        self.assertEqual(len(response.data['serie']), 7)

    def test_resumen_vacio_conserva_contrato(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/analitica/admin/resumen/?dias=14')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['kpis']['usuariosActivos'], 0)
        self.assertEqual(response.data['kpis']['tasaAbandono'], 0.0)
        self.assertEqual(response.data['modulos'], [])
        self.assertEqual(response.data['oportunidades'], [])
        self.assertEqual(len(response.data['serie']), 14)

    def test_tasa_abandono_usa_sesiones_y_nunca_supera_cien(self):
        eventos = [
            self.payload(evento='FORM_STARTED', resultado='STARTED', sesionId='sesion_form_001'),
            self.payload(evento='FORM_ABANDONED', resultado='ABANDONED', sesionId='sesion_form_001'),
            self.payload(evento='TASK_ABANDONED', resultado='ABANDONED', sesionId='sesion_form_001'),
        ]
        self.assertEqual(self.post(self.usuario, {'eventos': eventos}).status_code, 201)
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/analitica/admin/resumen/?dias=7')
        self.assertEqual(response.data['kpis']['tasaAbandono'], 100.0)


class DepurarEventosUsoTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user('retencion@test.mx', 'retencion@test.mx', 'Retencion2026!')

    def evento(self, antiguedad_dias):
        evento = EventoUso.objects.create(
            usuario=self.usuario,
            modulo='REPORTES', componente='PAGINA', evento='PAGE_VIEW', accion='NAVIGATE',
            resultado='COMPLETED', dispositivo='ESCRITORIO',
        )
        EventoUso.objects.filter(pk=evento.pk).update(fechaServidor=timezone.now() - timedelta(days=antiguedad_dias))
        return evento

    def test_dry_run_no_elimina_y_ejecucion_respeta_retencion(self):
        antiguo = self.evento(181)
        reciente = self.evento(20)
        salida = io.StringIO()
        call_command('depurar_eventos_uso', dias=180, dry_run=True, stdout=salida)
        self.assertIn('DRY-RUN: 1', salida.getvalue())
        self.assertTrue(EventoUso.objects.filter(pk=antiguo.pk).exists())
        call_command('depurar_eventos_uso', dias=180, stdout=io.StringIO())
        self.assertFalse(EventoUso.objects.filter(pk=antiguo.pk).exists())
        self.assertTrue(EventoUso.objects.filter(pk=reciente.pk).exists())

    def test_no_permite_retencion_menor_a_treinta_dias(self):
        with self.assertRaises(CommandError):
            call_command('depurar_eventos_uso', dias=29)
