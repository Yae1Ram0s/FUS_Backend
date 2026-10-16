import os
import tempfile
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APITransactionTestCase

from autenticacion.models import CorreoAutorizado
from catalogos.models import Estatus, MedioRecepcion, UnidadAdministrativa
from .estatus_efectivo import clave_chip
from .models import FUS, Evidencia, Turnado, Bitacora, Notificacion, Actividad, PushSubscription


class BitacoraROL2Tests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        for clave, tipo, orden in (
            ('Registrado', 'PARTICULAR', 1),
            ('Recibido', 'TITULAR', 2),
        ):
            Estatus.objects.get_or_create(
                clave=clave,
                defaults={'nombre': clave, 'tipoFlujo': tipo, 'orden': orden},
            )

        cls.rol1 = User.objects.create_user(
            username='dueno-bitacora@anam.gob.mx',
            email='dueno-bitacora@anam.gob.mx',
            password='x',
        )
        cls.rol2 = User.objects.create_user(
            username='titular-a@anam.gob.mx', email='titular-a@anam.gob.mx', password='x',
        )
        cls.otro_rol2 = User.objects.create_user(
            username='titular-b@anam.gob.mx', email='titular-b@anam.gob.mx', password='x',
        )
        for usuario, rol in ((cls.rol1, 'ROL1'), (cls.rol2, 'ROL2'), (cls.otro_rol2, 'ROL2')):
            CorreoAutorizado.objects.create(
                email=usuario.email,
                nombre=usuario.username,
                rol=rol,
                activo=1,
            )

        cls.fus_propio = FUS.objects.create(
            folio='FUS/BITACORA/ROL2/001',
            idSolicitanteInterno=cls.rol1,
            descripcion='FUS asignado al titular A',
            contexto='',
            estatusParticular_id='Registrado',
        )
        cls.fus_ajeno = FUS.objects.create(
            folio='FUS/BITACORA/ROL2/002',
            idSolicitanteInterno=cls.rol1,
            descripcion='FUS asignado al titular B',
            contexto='',
            estatusParticular_id='Registrado',
        )
        Turnado.objects.create(
            idFus=cls.fus_propio,
            idRemitente=cls.rol1,
            idDestinatario=cls.rol2,
            estatusTitular_id='Recibido',
        )
        Turnado.objects.create(
            idFus=cls.fus_ajeno,
            idRemitente=cls.rol1,
            idDestinatario=cls.otro_rol2,
            estatusTitular_id='Recibido',
        )

        Bitacora.objects.create(
            usuario=cls.rol2.email,
            rol='ROL2',
            accion='ASIGNACION_ESTADO',
            fusFolio=cls.fus_propio.folio,
            estadoAnterior='Turnado',
            estadoNuevo='Atendido',
        )
        Bitacora.objects.create(
            usuario=cls.rol2.email,
            rol='ROL2',
            accion='REGISTRO_RESPUESTA',
            fusFolio=cls.fus_propio.folio,
        )
        Bitacora.objects.create(
            usuario=cls.rol2.email,
            rol='ROL2',
            accion='ASIGNACION_ESTADO',
            fusFolio=cls.fus_propio.folio,
            estadoAnterior='En_seguimiento',
            estadoNuevo='Atendido',
        )
        Bitacora.objects.create(
            usuario=cls.otro_rol2.email,
            rol='ROL2',
            accion='REGISTRO_RESPUESTA',
            fusFolio=cls.fus_ajeno.folio,
        )
        Bitacora.objects.create(
            usuario=cls.rol1.email,
            rol='ROL1',
            accion='TURNAR_FUS',
            fusFolio=cls.fus_propio.folio,
            estadoAnterior='Registrado',
            estadoNuevo='Turnado',
        )

    def setUp(self):
        self.client.force_authenticate(self.rol2)

    def test_rol2_solo_recibe_sus_movimientos_de_fus_asignados(self):
        response = self.client.get('/api/bitacora/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total'], 3)
        self.assertTrue(all(r['usuario'] == self.rol2.email for r in response.data['results']))
        self.assertTrue(all(r['fusFolio'] == self.fus_propio.folio for r in response.data['results']))

    def test_rol2_ve_estados_traducidos_a_su_flujo(self):
        response = self.client.get('/api/bitacora/')
        transiciones = {(r['estadoAnterior'], r['estadoNuevo']) for r in response.data['results']}
        self.assertIn(('Recibido', 'En_seguimiento'), transiciones)
        self.assertIn(('En_seguimiento', 'Pendiente_validacion'), transiciones)

    def test_filtro_rol2_usa_estados_del_titular(self):
        en_seguimiento = self.client.get('/api/bitacora/?estatus_fus=En_seguimiento')
        pendiente = self.client.get('/api/bitacora/?estatus_fus=Pendiente_validacion')
        self.assertEqual(en_seguimiento.data['total'], 2)
        self.assertEqual(pendiente.data['total'], 1)

    def test_excel_y_pdf_respetan_filtros_y_columnas_seleccionadas(self):
        import io
        import openpyxl

        query = '?estatus_fus=Pendiente_validacion&columnas=folio,estatus'
        excel = self.client.get(f'/api/bitacora/exportar/excel/{query}')
        self.assertEqual(excel.status_code, status.HTTP_200_OK)
        self.assertEqual(
            excel['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

        libro = openpyxl.load_workbook(io.BytesIO(excel.content), read_only=True)
        hoja = libro.active
        filas = list(hoja.iter_rows(values_only=True))
        indice_encabezado = next(
            i for i, fila in enumerate(filas)
            if tuple(fila[:2]) == ('Folio', 'Estatus')
        )
        datos = [fila[:2] for fila in filas[indice_encabezado + 1:] if fila[0]]
        self.assertEqual(datos, [(self.fus_propio.folio, 'Pendiente de validación')])

        pdf = self.client.get(f'/api/bitacora/exportar/pdf/{query}')
        self.assertEqual(pdf.status_code, status.HTTP_200_OK)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))


class BitacoraROL1ExportTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.unidad = UnidadAdministrativa.objects.create(
            idUnidadAdministrativa=99001,
            clave='QA-BITACORA',
            unidadAdministrativa='Unidad de prueba Bitácora',
            esUnidadAdministrativa=1,
            activo=1,
        )
        cls.rol1 = User.objects.create_user(
            username='particular-bitacora@anam.gob.mx',
            email='particular-bitacora@anam.gob.mx',
            password='x',
        )
        cls.responsable = User.objects.create_user(
            username='responsable-bitacora@anam.gob.mx',
            email='responsable-bitacora@anam.gob.mx',
            password='x',
        )
        cls.otro_responsable = User.objects.create_user(
            username='otro-responsable@anam.gob.mx',
            email='otro-responsable@anam.gob.mx',
            password='x',
        )
        CorreoAutorizado.objects.create(
            email=cls.rol1.email, nombre='Particular de prueba', rol='ROL1', activo=1,
        )
        CorreoAutorizado.objects.create(
            email=cls.responsable.email,
            nombre='Responsable correcto',
            rol='ROL2',
            unidadAdministrativa=cls.unidad,
            activo=1,
        )
        CorreoAutorizado.objects.create(
            email=cls.otro_responsable.email, nombre='Responsable ajeno', rol='ROL2', activo=1,
        )
        Bitacora.objects.create(
            usuario=cls.responsable.email,
            rol='ROL2',
            accion='CONCLUSION_FUS',
            fusFolio='ANAM/PARTICULAR/FUS/ROL1/001',
            estadoAnterior='Pendiente_validacion',
            estadoNuevo='Concluido',
            observaciones='Movimiento que debe exportarse',
        )
        Bitacora.objects.create(
            usuario=cls.otro_responsable.email,
            rol='ROL2',
            accion='ASIGNACION_ESTADO',
            fusFolio='ANAM/PARTICULAR/FUS/ROL1/002',
            estadoAnterior='Turnado',
            estadoNuevo='Atendido',
            observaciones='Movimiento que debe quedar fuera',
        )

    def setUp(self):
        self.client.force_authenticate(self.rol1)

    def _query(self, columnas=None):
        from urllib.parse import urlencode
        from django.utils import timezone

        params = [
            ('q', 'FUS/ROL1/001'),
            ('usuario', self.responsable.email),
            ('unidadAdministrativa', str(self.unidad.idUnidadAdministrativa)),
            ('estatus_fus', 'Concluido'),
            ('fecha_desde', timezone.localdate().isoformat()),
            ('fecha_hasta', timezone.localdate().isoformat()),
            ('ordering', 'folio'),
        ]
        if columnas:
            params.append(('columnas', columnas))
        return f'?{urlencode(params)}'

    def test_lista_rol1_aplica_la_seleccion_combinada(self):
        response = self.client.get(f'/api/bitacora/{self._query()}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total'], 1)
        self.assertEqual(response.data['results'][0]['usuario'], self.responsable.email)
        self.assertEqual(response.data['results'][0]['estadoNuevo'], 'Concluido')

    def test_excel_rol1_conserva_filtros_orden_y_columnas(self):
        import io
        import openpyxl

        columnas = 'folio,nombre,usuario,estatus,estado_ant,estado_nuevo,observaciones'
        response = self.client.get(
            f'/api/bitacora/exportar/excel/{self._query(columnas)}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        libro = openpyxl.load_workbook(io.BytesIO(response.content), read_only=True)
        filas = list(libro.active.iter_rows(values_only=True))
        encabezado = ('Folio', 'Nombre', 'Usuario', 'Estatus', 'Estado anterior', 'Estado nuevo', 'Observaciones')
        indice = next(i for i, fila in enumerate(filas) if tuple(fila[:7]) == encabezado)
        datos = [fila[:7] for fila in filas[indice + 1:] if fila[0]]
        self.assertEqual(datos, [(
            'ANAM/PARTICULAR/FUS/ROL1/001',
            'Responsable correcto',
            self.responsable.email,
            'Concluido',
            'Pendiente de validación',
            'Concluido',
            'Movimiento que debe exportarse',
        )])

    def test_pdf_rol1_conserva_la_misma_seleccion(self):
        columnas = 'folio,nombre,estatus,observaciones'
        response = self.client.get(
            f'/api/bitacora/exportar/pdf/{self._query(columnas)}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))


class BitacoraEquipoParticularExportTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado',
            defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.unidad = UnidadAdministrativa.objects.create(
            idUnidadAdministrativa=99002,
            clave='QA-EQUIPO',
            unidadAdministrativa='Unidad visible del equipo',
            esUnidadAdministrativa=1,
            activo=1,
        )
        cls.propietario = User.objects.create_user(
            username='dueno-equipo-bitacora@anam.gob.mx',
            email='dueno-equipo-bitacora@anam.gob.mx',
            password='x',
        )
        cls.propietario_ajeno = User.objects.create_user(
            username='dueno-ajeno-bitacora@anam.gob.mx',
            email='dueno-ajeno-bitacora@anam.gob.mx',
            password='x',
        )
        cls.equipo = User.objects.create_user(
            username='equipo-bitacora@anam.gob.mx',
            email='equipo-bitacora@anam.gob.mx',
            password='x',
        )
        cls.responsable = User.objects.create_user(
            username='responsable-equipo@anam.gob.mx',
            email='responsable-equipo@anam.gob.mx',
            password='x',
        )
        cls.responsable_ajeno = User.objects.create_user(
            username='responsable-ajeno-equipo@anam.gob.mx',
            email='responsable-ajeno-equipo@anam.gob.mx',
            password='x',
        )
        CorreoAutorizado.objects.create(
            email=cls.propietario.email, nombre='Titular particular propio', rol='ROL1', activo=1,
        )
        CorreoAutorizado.objects.create(
            email=cls.propietario_ajeno.email, nombre='Titular particular ajeno', rol='ROL1', activo=1,
        )
        CorreoAutorizado.objects.create(
            email=cls.equipo.email,
            nombre='Equipo del titular propio',
            rol='EQUIPO_PARTICULAR',
            activo=1,
            idUsuarioRegistra=cls.propietario.id,
        )
        CorreoAutorizado.objects.create(
            email=cls.responsable.email,
            nombre='Responsable visible',
            rol='ROL2',
            unidadAdministrativa=cls.unidad,
            activo=1,
        )
        CorreoAutorizado.objects.create(
            email=cls.responsable_ajeno.email,
            nombre='Responsable oculto',
            rol='ROL2',
            activo=1,
        )
        cls.fus_propio = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/EQUIPO/001',
            idSolicitanteInterno=cls.propietario,
            descripcion='FUS del titular asociado',
            contexto='',
            estatusParticular_id='Registrado',
        )
        cls.fus_ajeno = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/EQUIPO/002',
            idSolicitanteInterno=cls.propietario_ajeno,
            descripcion='FUS de otra rama',
            contexto='',
            estatusParticular_id='Registrado',
        )
        Bitacora.objects.create(
            usuario=cls.responsable.email,
            rol='ROL2',
            accion='CONCLUSION_FUS',
            fusFolio=cls.fus_propio.folio,
            estadoAnterior='Pendiente_validacion',
            estadoNuevo='Concluido',
            observaciones='Movimiento visible para el equipo',
        )
        Bitacora.objects.create(
            usuario=cls.responsable_ajeno.email,
            rol='ROL2',
            accion='CONCLUSION_FUS',
            fusFolio=cls.fus_ajeno.folio,
            estadoAnterior='Pendiente_validacion',
            estadoNuevo='Concluido',
            observaciones='Movimiento de otra rama',
        )

    def setUp(self):
        self.client.force_authenticate(self.equipo)

    def _query(self, columnas=None):
        from urllib.parse import urlencode
        from django.utils import timezone

        params = [
            ('q', 'Responsable visible'),
            ('usuario', self.responsable.email),
            ('unidadAdministrativa', str(self.unidad.idUnidadAdministrativa)),
            ('estatus_fus', 'Concluido'),
            ('fecha_desde', timezone.localdate().isoformat()),
            ('fecha_hasta', timezone.localdate().isoformat()),
            ('ordering', 'folio'),
        ]
        if columnas:
            params.append(('columnas', columnas))
        return f'?{urlencode(params)}'

    def test_equipo_solo_ve_la_rama_de_su_titular_y_aplica_filtros(self):
        response = self.client.get(f'/api/bitacora/{self._query()}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total'], 1)
        self.assertEqual(response.data['results'][0]['fusFolio'], self.fus_propio.folio)

    def test_opciones_de_responsable_no_exponen_otras_ramas(self):
        response = self.client.get('/api/bitacora/responsables/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['email'] for item in response.data], [self.responsable.email])
        self.assertEqual(response.data[0]['unidadAdministrativa'], self.unidad.idUnidadAdministrativa)

    def test_excel_y_pdf_del_equipo_conservan_seleccion(self):
        import io
        import openpyxl

        columnas = 'folio,nombre,usuario,unidadAdministrativa,estatus,observaciones'
        excel = self.client.get(f'/api/bitacora/exportar/excel/{self._query(columnas)}')
        self.assertEqual(excel.status_code, status.HTTP_200_OK)
        libro = openpyxl.load_workbook(io.BytesIO(excel.content), read_only=True)
        filas = list(libro.active.iter_rows(values_only=True))
        encabezado = ('Folio', 'Nombre', 'Usuario', 'Unidad administrativa', 'Estatus', 'Observaciones')
        indice = next(i for i, fila in enumerate(filas) if tuple(fila[:6]) == encabezado)
        datos = [fila[:6] for fila in filas[indice + 1:] if fila[0]]
        self.assertEqual(datos, [(
            self.fus_propio.folio,
            'Responsable visible',
            self.responsable.email,
            self.unidad.unidadAdministrativa,
            'Concluido',
            'Movimiento visible para el equipo',
        )])

        pdf = self.client.get(f'/api/bitacora/exportar/pdf/{self._query(columnas)}')
        self.assertEqual(pdf.status_code, status.HTTP_200_OK)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))


class ReportesTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado',
            defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.rol1 = User.objects.create_user(
            username='reportes@anam.gob.mx', email='reportes@anam.gob.mx', password='x',
        )
        CorreoAutorizado.objects.create(
            email=cls.rol1.email, nombre='Usuario Reportes', rol='ROL1', activo=1,
        )
        cls.rol2 = User.objects.create_user(
            username='sinreportes@anam.gob.mx', email='sinreportes@anam.gob.mx', password='x',
        )
        CorreoAutorizado.objects.create(
            email=cls.rol2.email, nombre='Sin Reportes', rol='ROL2', activo=1,
        )
        FUS.objects.create(
            folio='FUS/REPORTES/001', idSolicitanteInterno=cls.rol1,
            descripcion='Solicitud para indicadores', contexto='',
            prioridad='Alta', estatusParticular_id='Registrado',
        )

    def test_rol1_consulta_resumen(self):
        self.client.force_authenticate(self.rol1)
        response = self.client.get('/api/reportes/resumen/?fecha_inicio=2020-01-01&fecha_fin=2030-01-01')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['resumen']['total'], 1)
        self.assertIn('evolucion', response.data)
        self.assertIn('detalle', response.data)

    def test_rol2_no_puede_consultar_reportes(self):
        self.client.force_authenticate(self.rol2)
        response = self.client.get('/api/reportes/resumen/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_exportaciones_generan_archivo(self):
        self.client.force_authenticate(self.rol1)
        for formato, content_type in (
            ('pdf', 'application/pdf'),
            ('excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'),
        ):
            response = self.client.post(
                f'/api/reportes/exportar/{formato}/?fecha_inicio=2020-01-01&fecha_fin=2030-01-01',
                {'secciones': ['resumen', 'detalle']},
                format='json',
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response['Content-Type'], content_type)
            self.assertGreater(len(response.content), 100)


class FUSIDORTests(APITestCase):
    """Un usuario ROL1 no debe poder ver/editar/turnar un FUS que no le pertenece
    (IDOR): debe recibir 404, no 403 ni 200, para no confirmar la existencia del recurso."""

    @classmethod
    def setUpTestData(cls):
        cls.estatus_registrado, _ = Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)

        cls.user_a = User.objects.create_user(username='a@anam.gob.mx', email='a@anam.gob.mx', password='x')
        CorreoAutorizado.objects.create(email='a@anam.gob.mx', nombre='Usuario A', rol='ROL1', activo=1)

        cls.user_b = User.objects.create_user(username='b@anam.gob.mx', email='b@anam.gob.mx', password='x')
        CorreoAutorizado.objects.create(email='b@anam.gob.mx', nombre='Usuario B', rol='ROL1', activo=1)

        cls.user_dest = User.objects.create_user(username='dest@anam.gob.mx', email='dest@anam.gob.mx', password='x')
        CorreoAutorizado.objects.create(email='dest@anam.gob.mx', nombre='Destinatario', rol='ROL2', activo=1)

        cls.fus_de_b = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0001/2026',
            idSolicitanteInterno=cls.user_b,
            descripcion='Solicitud de B',
            contexto='',
            estatusParticular_id='Registrado',
            idUsuarioRegistra=cls.user_b.id,
        )

    def test_get_fus_ajeno_devuelve_404(self):
        self.client.force_authenticate(user=self.user_a)
        resp = self.client.get(f'/api/fus/{self.fus_de_b.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_fus_ajeno_devuelve_404(self):
        self.client.force_authenticate(user=self.user_a)
        resp = self.client.patch(f'/api/fus/{self.fus_de_b.pk}/', {'descripcion': 'hackeado'})
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.fus_de_b.refresh_from_db()
        self.assertEqual(self.fus_de_b.descripcion, 'Solicitud de B')

    def test_turnar_fus_ajeno_devuelve_404(self):
        self.client.force_authenticate(user=self.user_a)
        resp = self.client.post(f'/api/fus/{self.fus_de_b.pk}/turnar/', {
            'destinatarios': [{'idDestinatario': self.user_dest.id, 'idMedio': self.medio.id}],
            'solicitudTexto': 'intento de turnado ajeno',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_actividad_fus_ajeno_devuelve_404(self):
        self.client.force_authenticate(user=self.user_a)
        resp = self.client.get(f'/api/fus/{self.fus_de_b.pk}/actividad/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_dueno_si_puede_ver_su_propio_fus(self):
        self.client.force_authenticate(user=self.user_b)
        resp = self.client.get(f'/api/fus/{self.fus_de_b.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class TurnarMultiplesDestinatariosTests(APITestCase):
    """TurnarFUSView — Bloque N: turnar a varios destinatarios del mismo FUS
    con el mismo medio no debe repetir la consulta a MedioRecepcion ni el
    get_or_create de la Actividad de "vence FUS" una vez por destinatario."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        Estatus.objects.get_or_create(
            clave='Recibido', defaults={'nombre': 'Recibido', 'tipoFlujo': 'TITULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='rol1@t.mx', email='rol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.dest1 = User.objects.create_user(username='dest1@t.mx', email='dest1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='dest1@t.mx', nombre='Dest1', rol='ROL2', activo=1)
        cls.dest2 = User.objects.create_user(username='dest2@t.mx', email='dest2@t.mx', password='x')
        CorreoAutorizado.objects.create(email='dest2@t.mx', nombre='Dest2', rol='ROL2', activo=1)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0400/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='Registrado',
            idUsuarioRegistra=cls.rol1.id,
            fechaLimite=timezone.now() + timedelta(days=3),
        )

    def test_turnar_a_dos_destinatarios_mismo_medio(self):
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/turnar/', {
            'destinatarios': [
                {'idDestinatario': self.dest1.id, 'idMedio': self.medio.id},
                {'idDestinatario': self.dest2.id, 'idMedio': self.medio.id},
            ],
            'solicitudTexto': 'turnado de prueba',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        turnados = Turnado.objects.filter(idFus=self.fus, activo=1)
        self.assertEqual(turnados.count(), 2)
        self.assertEqual(set(turnados.values_list('idDestinatario_id', flat=True)), {self.dest1.id, self.dest2.id})

        # Una sola Actividad "vence FUS" para el FUS, con ambos destinatarios
        # como participantes — no una por destinatario.
        actividades = Actividad.objects.filter(idFusRelacionado=self.fus, tipo='limite')
        self.assertEqual(actividades.count(), 1)
        self.assertEqual(
            set(actividades.first().participantes.values_list('id', flat=True)),
            {self.dest1.id, self.dest2.id},
        )

    def test_medio_recepcion_se_consulta_una_sola_vez_para_ambos_destinatarios(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        self.client.force_authenticate(user=self.rol1)
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.post(f'/api/fus/{self.fus.pk}/turnar/', {
                'destinatarios': [
                    {'idDestinatario': self.dest1.id, 'idMedio': self.medio.id},
                    {'idDestinatario': self.dest2.id, 'idMedio': self.medio.id},
                ],
                'solicitudTexto': 'turnado de prueba',
            }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        consultas_medio = [q for q in ctx.captured_queries if 'scs_cat_medios_recepcion' in q['sql']]
        # SELECT del medio (una sola vez, cacheado por id) — no debe haber
        # una segunda SELECT a MedioRecepcion para el segundo destinatario.
        selects_medio = [q for q in consultas_medio if q['sql'].strip().upper().startswith('SELECT')]
        self.assertEqual(len(selects_medio), 1, consultas_medio)


class ComisionarFUSActividadTests(APITestCase):
    """ComisionarFUSView — el comisionado asignado debe quedar como
    participante de la Actividad "vence FUS" del calendario, igual que ya
    pasa con el destinatario de un Turnado (TurnarMultiplesDestinatariosTests)
    — sin esto, la temporalidad del FUS nunca aparecía en el calendario del
    comisionado, solo en el de quien lo registró/turnó."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.rol1 = User.objects.create_user(username='rol1@t.mx', email='rol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.comisionado = User.objects.create_user(username='comi@t.mx', email='comi@t.mx', password='x')
        CorreoAutorizado.objects.create(email='comi@t.mx', nombre='Comi', rol='COMISIONADO', activo=1)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0500/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='Registrado',
            idUsuarioRegistra=cls.rol1.id,
            fechaLimite=timezone.now() + timedelta(days=3),
        )

    def test_comisionar_agrega_al_comisionado_como_participante(self):
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/comisionar/', {
            'comisionado_id': self.comisionado.id,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        actividad = Actividad.objects.get(idFusRelacionado=self.fus, tipo='limite', activo=1)
        self.assertIn(self.comisionado.id, actividad.participantes.values_list('id', flat=True))


class FiltroPendienteValidacionTests(APITestCase):
    """FUSListCreateView — con un solo Titular turnado (sin comisionar),
    marcar "Atendido" deja fus.estatusParticular en 'Atendido'
    (MarcarTurnadoAtendidoView, turnado.py); es el propio Turnado el que pasa
    a 'Pendiente_validacion'. La tarjeta ya lo muestra como "Por validar"
    vía FUSSerializer.get_estatusVisual (pasa el estatus del único turnado
    activo) — el filtro ?estatusParticular=Pendiente_validacion debe
    encontrar ese mismo FUS, no solo los que ya llegaron a
    'Pendiente_validacion' a nivel FUS (flujo de comisionado)."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='rol1@t.mx', email='rol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.dest = User.objects.create_user(username='dest@t.mx', email='dest@t.mx', password='x')
        CorreoAutorizado.objects.create(email='dest@t.mx', nombre='Dest', rol='ROL2', activo=1)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0600/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='Atendido',
            idUsuarioRegistra=cls.rol1.id,
        )
        Turnado.objects.create(
            idFus=cls.fus, idRemitente=cls.rol1, idDestinatario=cls.dest,
            idMedio=cls.medio, estatusTitular_id='Pendiente_validacion', activo=1,
        )

    def test_filtro_por_validar_encuentra_fus_con_un_solo_turnado(self):
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.get('/api/fus/', {'estatusParticular': 'Pendiente_validacion'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        folios = {item['folio'] for item in resp.data['results']}
        self.assertIn(self.fus.folio, folios)

    def test_filtro_por_validar_no_incluye_fus_con_varios_turnados_atendido(self):
        # Con dos personas turnadas, "Atendido" a nivel FUS no implica que
        # AMBAS ya estén listas para validación — solo una lo está aquí, así
        # que no debe colarse con la misma lógica de "un solo turnado".
        dest2 = User.objects.create_user(username='dest2@t.mx', email='dest2@t.mx', password='x')
        CorreoAutorizado.objects.create(email='dest2@t.mx', nombre='Dest2', rol='ROL2', activo=1)
        fus2 = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0601/2026', idSolicitanteInterno=self.rol1,
            descripcion='x', contexto='', estatusParticular_id='Atendido',
            idUsuarioRegistra=self.rol1.id,
        )
        Turnado.objects.create(
            idFus=fus2, idRemitente=self.rol1, idDestinatario=self.dest,
            idMedio=self.medio, estatusTitular_id='Pendiente_validacion', activo=1,
        )
        Turnado.objects.create(
            idFus=fus2, idRemitente=self.rol1, idDestinatario=dest2,
            idMedio=self.medio, estatusTitular_id='En_seguimiento', activo=1,
        )
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.get('/api/fus/', {'estatusParticular': 'Pendiente_validacion'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        folios = {item['folio'] for item in resp.data['results']}
        self.assertNotIn(fus2.folio, folios)


class ConteosPorChipNoDependenDelFiltroActivoTests(APITestCase):
    """FUSListCreateView / MisTurnadosView — el número que se muestra junto a
    cada chip debe reflejar TODA la bandeja (mismo search/scope), no solo lo
    que ya trae aplicado el chip seleccionado: antes `conteoEstatus` se
    calculaba en el frontend sobre `lista`, que el backend ya devolvía
    filtrada por el chip activo, así que en cuanto se elegía uno los demás
    chips se veían en 0 aunque sí hubiera resultados."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='rol1g@t.mx', email='rol1g@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1g@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.rol2 = User.objects.create_user(username='rol2g@t.mx', email='rol2g@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol2g@t.mx', nombre='Rol2', rol='ROL2', activo=1)

        cls.fus_registrado = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0900/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='Registrado',
            idUsuarioRegistra=cls.rol1.id,
        )
        cls.fus_turnado = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0901/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='Turnado',
            idUsuarioRegistra=cls.rol1.id,
        )
        cls.turnado = Turnado.objects.create(
            idFus=cls.fus_turnado, idRemitente=cls.rol1, idDestinatario=cls.rol2,
            idMedio=cls.medio, estatusTitular_id='Recibido', activo=1,
        )

    def test_fus_conteos_no_se_reducen_al_chip_activo(self):
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.get('/api/fus/', {'estatusParticular': 'Turnado'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        folios = {item['folio'] for item in resp.data['results']}
        self.assertEqual(folios, {self.fus_turnado.folio})

        conteos = resp.data['conteos']['estatus']
        self.assertEqual(conteos['Registrado'], 1)
        self.assertEqual(conteos['Turnado'], 1)

    def test_turnados_conteos_no_se_reducen_al_chip_activo(self):
        # Un segundo turnado 'En_seguimiento' para tener dos claves distintas
        # en la bandeja de ROL2 y confirmar que el chip inactivo ('Recibido')
        # sigue contando aunque el filtro activo sea 'En_seguimiento'.
        fus3 = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0902/2026', idSolicitanteInterno=self.rol1,
            descripcion='x', contexto='', estatusParticular_id='En_seguimiento',
            idUsuarioRegistra=self.rol1.id,
        )
        Turnado.objects.create(
            idFus=fus3, idRemitente=self.rol1, idDestinatario=self.rol2,
            idMedio=self.medio, estatusTitular_id='En_seguimiento', activo=1,
        )
        self.client.force_authenticate(user=self.rol2)
        resp = self.client.get('/api/turnados/mis-turnados/', {'estatusTitular': 'En_seguimiento'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        folios = {item['idFus']['folio'] for item in resp.data['results']}
        self.assertEqual(folios, {fus3.folio})

        conteos = resp.data['conteos']['estatus']
        self.assertEqual(conteos['Recibido'], 1)
        self.assertEqual(conteos['En_seguimiento'], 1)


class EstatusVisualReciboNoSustituyeTurnadoTests(APITestCase):
    """FUSSerializer.get_estatusVisual — con un solo Titular turnado que
    todavía no ha hecho nada (Turnado.estatusTitular arranca en 'Recibido'),
    la tarjeta de Rol 1 debe seguir mostrando "Turnado" (el estatus agregado
    del FUS), no "Recibido": ese estado inicial no le dice nada nuevo a Rol 1
    y se veía como si el sistema hubiera perdido el estatus real. En cuanto
    el Titular avanza (aquí probado con 'En_seguimiento'), el passthrough al
    estatus del turnado sigue aplicando normal."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='rol1f@t.mx', email='rol1f@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1f@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.dest = User.objects.create_user(username='destf@t.mx', email='destf@t.mx', password='x')
        CorreoAutorizado.objects.create(email='destf@t.mx', nombre='Dest', rol='ROL2', activo=1)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0800/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='Turnado',
            idUsuarioRegistra=cls.rol1.id,
        )
        cls.turnado = Turnado.objects.create(
            idFus=cls.fus, idRemitente=cls.rol1, idDestinatario=cls.dest,
            idMedio=cls.medio, estatusTitular_id='Recibido', activo=1,
        )

    def test_recibido_muestra_turnado_no_recibido(self):
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.get('/api/fus/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        item = next(r for r in resp.data['results'] if r['folio'] == self.fus.folio)
        self.assertEqual(item['estatusVisual'], 'Turnado')

    def test_en_seguimiento_sigue_pasando_directo(self):
        self.turnado.estatusTitular_id = 'En_seguimiento'
        self.turnado.save()
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.get('/api/fus/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        item = next(r for r in resp.data['results'] if r['folio'] == self.fus.folio)
        self.assertEqual(item['estatusVisual'], 'En_seguimiento')


class SeguimientoComisionadoNotificaAlTitularTests(APITestCase):
    """SeguimientoComisionadoListCreateView.post — cuando el FUS llegó al
    comisionado vía un Turnado (el Titular lo delegó en vez de responder
    directo), ese Titular debe enterarse de que el comisionado ya empezó a
    atenderlo. Antes el cálculo de destinatarios solo consideraba el lado del
    Particular (unidad del comisionado + equipo del dueño del FUS), dejando
    al Titular sin ninguna notificación."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='rol1@t.mx', email='rol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.rol2 = User.objects.create_user(username='rol2@t.mx', email='rol2@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol2@t.mx', nombre='Rol2', rol='ROL2', activo=1)
        cls.comisionado = User.objects.create_user(username='comi@t.mx', email='comi@t.mx', password='x')
        CorreoAutorizado.objects.create(email='comi@t.mx', nombre='Comi', rol='COMISIONADO', activo=1)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0700/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='En_seguimiento',
            idUsuarioRegistra=cls.rol1.id, idComisionado=cls.comisionado,
        )
        Turnado.objects.create(
            idFus=cls.fus, idRemitente=cls.rol1, idDestinatario=cls.rol2,
            idMedio=cls.medio, estatusTitular_id='En_seguimiento', activo=1,
        )

    def test_titular_recibe_notificacion_al_primer_avance_del_comisionado(self):
        self.client.force_authenticate(user=self.comisionado)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/seguimiento/', {
            'descripcionActividad': 'Ya empecé a revisar el expediente.',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

        self.assertTrue(
            Notificacion.objects.filter(
                idDestinatario=self.rol2, fusFolio=self.fus.folio, tipoEvento='SEGUIMIENTO_FINALIZADO',
            ).exists()
        )


class SeguimientoComisionadoNotificaAlDuenoEnOtraUnidadTests(APITestCase):
    """SeguimientoComisionadoListCreateView.post — el cálculo de destinatarios
    "lado del Particular" resolvía la unidad del COMISIONADO, no la del dueño
    real del FUS (idSolicitanteInterno). Si el FUS llegó al comisionado vía un
    Turnado a un Rol 2 de otra unidad (que comisiona desde ahí, ver
    FUSComisionadosDisponiblesView), el comisionado termina en una unidad
    distinta a la del Rol 1 original — y ese Rol 1 se quedaba sin
    notificación aunque el FUS siguiera siendo suyo."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        unidad_rol1 = UnidadAdministrativa.objects.create(
            idUnidadAdministrativa=99010, unidadAdministrativa='Dirección A', esUnidadAdministrativa=1, activo=1,
        )
        unidad_comisionado = UnidadAdministrativa.objects.create(
            idUnidadAdministrativa=99011, unidadAdministrativa='Dirección B', esUnidadAdministrativa=1, activo=1,
        )
        cls.rol1 = User.objects.create_user(username='rol1u@t.mx', email='rol1u@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1u@t.mx', nombre='Rol1', rol='ROL1', activo=1, unidadAdministrativa=unidad_rol1)
        cls.rol2 = User.objects.create_user(username='rol2u@t.mx', email='rol2u@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol2u@t.mx', nombre='Rol2', rol='ROL2', activo=1, unidadAdministrativa=unidad_comisionado)
        cls.comisionado = User.objects.create_user(username='comiu@t.mx', email='comiu@t.mx', password='x')
        CorreoAutorizado.objects.create(email='comiu@t.mx', nombre='Comi', rol='COMISIONADO', activo=1, unidadAdministrativa=unidad_comisionado)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0703/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='En_seguimiento',
            idUsuarioRegistra=cls.rol1.id, idComisionado=cls.comisionado,
        )
        Turnado.objects.create(
            idFus=cls.fus, idRemitente=cls.rol1, idDestinatario=cls.rol2,
            idMedio=cls.medio, estatusTitular_id='En_seguimiento', activo=1,
        )

    def test_dueno_original_recibe_notificacion_aunque_el_comisionado_sea_de_otra_unidad(self):
        self.client.force_authenticate(user=self.comisionado)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/seguimiento/', {
            'descripcionActividad': 'Ya empecé a revisar el expediente.',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

        self.assertTrue(
            Notificacion.objects.filter(
                idDestinatario=self.rol1, fusFolio=self.fus.folio, tipoEvento='SEGUIMIENTO_FINALIZADO',
            ).exists()
        )


class SeguimientoComisionadoPermiteTitularQueComisionoTests(APITestCase):
    """SeguimientoComisionadoListCreateView.post — una vez que Rol 2 comisiona
    un FUS, tanto el Comisionado asignado como ese mismo Rol 2 (destinatario
    del Turnado) pueden registrar seguimiento; un Rol 2 ajeno a este FUS, y
    Rol 1, siguen sin poder (ver EsComisionadoAsignado)."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='rol1d@t.mx', email='rol1d@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1d@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.rol2 = User.objects.create_user(username='rol2d@t.mx', email='rol2d@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol2d@t.mx', nombre='Rol2', rol='ROL2', activo=1)
        cls.otro_rol2 = User.objects.create_user(username='otro2d@t.mx', email='otro2d@t.mx', password='x')
        CorreoAutorizado.objects.create(email='otro2d@t.mx', nombre='Otro Rol2', rol='ROL2', activo=1)
        cls.comisionado = User.objects.create_user(username='comid@t.mx', email='comid@t.mx', password='x')
        CorreoAutorizado.objects.create(email='comid@t.mx', nombre='Comi', rol='COMISIONADO', activo=1)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0702/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='En_seguimiento',
            idUsuarioRegistra=cls.rol1.id, idComisionado=cls.comisionado,
        )
        Turnado.objects.create(
            idFus=cls.fus, idRemitente=cls.rol1, idDestinatario=cls.rol2,
            idMedio=cls.medio, estatusTitular_id='En_seguimiento', activo=1,
        )

    def test_rol2_destinatario_puede_agregar_seguimiento(self):
        self.client.force_authenticate(user=self.rol2)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/seguimiento/', {
            'descripcionActividad': 'Ya hablé con el área.',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_comisionado_sigue_pudiendo_agregar_seguimiento(self):
        self.client.force_authenticate(user=self.comisionado)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/seguimiento/', {
            'descripcionActividad': 'Reviso el expediente.',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_rol2_ajeno_a_este_fus_no_puede_agregar_seguimiento(self):
        self.client.force_authenticate(user=self.otro_rol2)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/seguimiento/', {
            'descripcionActividad': 'No debería poder.',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN, resp.data)

    def test_rol1_no_puede_agregar_seguimiento(self):
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/seguimiento/', {
            'descripcionActividad': 'No debería poder.',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN, resp.data)

    def test_solo_accion_por_emprender_se_acepta_y_clasifica_como_tal(self):
        self.client.force_authenticate(user=self.comisionado)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/seguimiento/', {
            'accionTexto': 'Solicitar el expediente físico.',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data['tipo'], 'accion_por_emprender')
        self.assertEqual(resp.data['accionTexto'], 'Solicitar el expediente físico.')

    def test_seguimiento_vacio_se_rechaza(self):
        self.client.force_authenticate(user=self.comisionado)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/seguimiento/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)


class SeguimientoComisionadoNotificaConNombreDeRol2Tests(APITestCase):
    """SeguimientoComisionadoListCreateView.post — cuando quien ejecutó
    "comisionar" fue Rol 2 (no Rol 1), el primer avance del Comisionado
    notifica a Rol 1 firmado con el nombre de ese Rol 2 ("Ana Titular
    comenzó a atender..."), no con el genérico "El comisionado..." — de cara
    al Particular, el responsable visible sigue siendo el Titular que
    delegó."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='rol1e@t.mx', email='rol1e@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1e@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.rol2 = User.objects.create_user(username='rol2e@t.mx', email='rol2e@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol2e@t.mx', nombre='Ana Titular', rol='ROL2', activo=1)
        cls.comisionado = User.objects.create_user(username='comie@t.mx', email='comie@t.mx', password='x')
        CorreoAutorizado.objects.create(email='comie@t.mx', nombre='Comi', rol='COMISIONADO', activo=1)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0703/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='Turnado',
            idUsuarioRegistra=cls.rol1.id,
        )
        Turnado.objects.create(
            idFus=cls.fus, idRemitente=cls.rol1, idDestinatario=cls.rol2,
            idMedio=cls.medio, estatusTitular_id='Recibido', activo=1,
        )

    def test_mensaje_usa_el_nombre_de_rol2_que_comisiono(self):
        self.client.force_authenticate(user=self.rol2)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/comisionar/', {
            'comisionado_id': self.comisionado.id,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        self.client.force_authenticate(user=self.comisionado)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/seguimiento/', {
            'descripcionActividad': 'Ya empecé a revisar el expediente.',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

        notif = Notificacion.objects.get(idDestinatario=self.rol1, fusFolio=self.fus.folio)
        self.assertIn('Ana Titular comenzó a atender el FUS', notif.mensaje)


class AtendidoFUSNotificaAlTitularTests(APITestCase):
    """AtendidoFUSView — mismo criterio que SeguimientoComisionadoNotificaAlTitularTests:
    si el FUS llegó al comisionado vía un Turnado, ese Titular también debe
    enterarse cuando se manda a validación del Particular."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='rol1b@t.mx', email='rol1b@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1b@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.rol2 = User.objects.create_user(username='rol2b@t.mx', email='rol2b@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol2b@t.mx', nombre='Rol2', rol='ROL2', activo=1)
        cls.comisionado = User.objects.create_user(username='comib@t.mx', email='comib@t.mx', password='x')
        CorreoAutorizado.objects.create(email='comib@t.mx', nombre='Comi', rol='COMISIONADO', activo=1)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0701/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='Atendido',
            idUsuarioRegistra=cls.rol1.id, idComisionado=cls.comisionado,
        )
        Turnado.objects.create(
            idFus=cls.fus, idRemitente=cls.rol1, idDestinatario=cls.rol2,
            idMedio=cls.medio, estatusTitular_id='En_seguimiento', activo=1,
        )

    def test_titular_recibe_notificacion_al_enviar_a_validacion(self):
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/atendido/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        self.assertTrue(
            Notificacion.objects.filter(
                idDestinatario=self.rol2, fusFolio=self.fus.folio, tipoEvento='SEGUIMIENTO_FINALIZADO',
            ).exists()
        )


class AtendidoFUSNotificaAlDuenoEnOtraUnidadTests(APITestCase):
    """AtendidoFUSView — mismo caso que
    SeguimientoComisionadoNotificaAlDuenoEnOtraUnidadTests: el dueño real del
    FUS debe enterarse de que ya se mandó a validación aunque el comisionado
    asignado sea de otra unidad administrativa."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        unidad_rol1 = UnidadAdministrativa.objects.create(
            idUnidadAdministrativa=99012, unidadAdministrativa='Dirección C', esUnidadAdministrativa=1, activo=1,
        )
        unidad_comisionado = UnidadAdministrativa.objects.create(
            idUnidadAdministrativa=99013, unidadAdministrativa='Dirección D', esUnidadAdministrativa=1, activo=1,
        )
        cls.rol1 = User.objects.create_user(username='rol1v@t.mx', email='rol1v@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1v@t.mx', nombre='Rol1', rol='ROL1', activo=1, unidadAdministrativa=unidad_rol1)
        cls.rol2 = User.objects.create_user(username='rol2v@t.mx', email='rol2v@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol2v@t.mx', nombre='Rol2', rol='ROL2', activo=1, unidadAdministrativa=unidad_comisionado)
        cls.comisionado = User.objects.create_user(username='comiv@t.mx', email='comiv@t.mx', password='x')
        CorreoAutorizado.objects.create(email='comiv@t.mx', nombre='Comi', rol='COMISIONADO', activo=1, unidadAdministrativa=unidad_comisionado)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0704/2026', idSolicitanteInterno=cls.rol1,
            descripcion='x', contexto='', estatusParticular_id='Atendido',
            idUsuarioRegistra=cls.rol1.id, idComisionado=cls.comisionado,
        )
        Turnado.objects.create(
            idFus=cls.fus, idRemitente=cls.rol1, idDestinatario=cls.rol2,
            idMedio=cls.medio, estatusTitular_id='En_seguimiento', activo=1,
        )

    def test_dueno_original_recibe_notificacion_aunque_el_comisionado_sea_de_otra_unidad(self):
        # Lo dispara rol2 (destinatario del Turnado), no rol1: si fuera rol1
        # quien lo dispara, `destinatarios.discard(user)` lo quitaría de su
        # propia notificación y la prueba no distinguiría "nunca se agregó"
        # de "se agregó y luego se descartó por ser el actor".
        self.client.force_authenticate(user=self.rol2)
        resp = self.client.post(f'/api/fus/{self.fus.pk}/atendido/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        self.assertTrue(
            Notificacion.objects.filter(
                idDestinatario=self.rol1, fusFolio=self.fus.folio, tipoEvento='SEGUIMIENTO_FINALIZADO',
            ).exists()
        )


class RevisarSlaNotificaComisionadoTests(APITestCase):
    """revisar_sla (management command) — el comisionado asignado a un FUS
    con fecha límite próxima a vencer debe recibir el aviso de SLA, no solo
    el dueño del FUS y el Titular que lo turnó."""

    def test_comisionado_recibe_aviso_de_sla(self):
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        rol1 = User.objects.create_user(username='rol1c@t.mx', email='rol1c@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1c@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        comisionado = User.objects.create_user(username='comic@t.mx', email='comic@t.mx', password='x')
        CorreoAutorizado.objects.create(email='comic@t.mx', nombre='Comi', rol='COMISIONADO', activo=1)

        fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0702/2026', idSolicitanteInterno=rol1,
            descripcion='x', contexto='', estatusParticular_id='En_seguimiento',
            idUsuarioRegistra=rol1.id, idComisionado=comisionado,
            fechaLimite=timezone.now() + timedelta(hours=1),
        )

        call_command('revisar_sla')

        self.assertTrue(
            Notificacion.objects.filter(
                idDestinatario=comisionado, fusFolio=fus.folio, tipoEvento='SLA_POR_VENCER',
            ).exists()
        )


class SlaVencidoYProrrogaTests(APITestCase):
    """revisar_sla avisa de los FUS ya vencidos (una vez por fecha límite) y
    el Particular dueño puede darles prórroga de fecha."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        Estatus.objects.get_or_create(
            clave='En_seguimiento', defaults={'nombre': 'En seguimiento', 'tipoFlujo': 'PARTICULAR', 'orden': 2},
        )
        Estatus.objects.get_or_create(
            clave='Concluido', defaults={'nombre': 'Concluido', 'tipoFlujo': 'PARTICULAR', 'orden': 3},
        )
        cls.rol1 = User.objects.create_user(username='rol1p@t.mx', email='rol1p@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1p@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.otro_rol1 = User.objects.create_user(username='otrop@t.mx', email='otrop@t.mx', password='x')
        CorreoAutorizado.objects.create(email='otrop@t.mx', nombre='Otro', rol='ROL1', activo=1)
        cls.comisionado = User.objects.create_user(username='comip@t.mx', email='comip@t.mx', password='x')
        CorreoAutorizado.objects.create(email='comip@t.mx', nombre='Comi', rol='COMISIONADO', activo=1)

    def _fus(self, folio, limite, estatus='En_seguimiento'):
        from django.utils import timezone
        return FUS.objects.create(
            folio=folio, idSolicitanteInterno=self.rol1, descripcion='x', contexto='',
            estatusParticular_id=estatus, idUsuarioRegistra=self.rol1.id,
            idComisionado=self.comisionado, fechaLimite=limite,
        )

    def test_revisar_sla_avisa_de_fus_vencido_una_sola_vez(self):
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        fus = self._fus('ANAM/PARTICULAR/FUS/0801/2026', timezone.now() - timedelta(days=1))

        call_command('revisar_sla')
        call_command('revisar_sla')

        for dest in (self.rol1, self.comisionado):
            self.assertEqual(
                Notificacion.objects.filter(
                    idDestinatario=dest, fusFolio=fus.folio, tipoEvento='SLA_VENCIDO',
                ).count(), 1,
            )

    def test_revisar_sla_no_avisa_vencido_si_ya_concluido(self):
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        fus = self._fus('ANAM/PARTICULAR/FUS/0802/2026', timezone.now() - timedelta(days=1), estatus='Concluido')
        call_command('revisar_sla')
        self.assertFalse(Notificacion.objects.filter(fusFolio=fus.folio, tipoEvento='SLA_VENCIDO').exists())

    def test_prorroga_actualiza_fecha_limite_y_notifica(self):
        from datetime import timedelta

        from django.utils import timezone

        fus = self._fus('ANAM/PARTICULAR/FUS/0803/2026', timezone.now() - timedelta(days=1))
        nueva = timezone.now() + timedelta(days=5)
        self.client.force_authenticate(user=self.rol1)

        resp = self.client.post(
            f'/api/fus/{fus.id}/prorroga/',
            {'fechaLimite': nueva.isoformat(), 'motivo': 'Falta información'}, format='json',
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        fus.refresh_from_db()
        self.assertAlmostEqual(fus.fechaLimite, nueva, delta=timedelta(seconds=1))
        self.assertEqual(resp.data['estadoTemporalidad'], None)
        self.assertTrue(Bitacora.objects.filter(fusFolio=fus.folio, accion='PRORROGA_FUS').exists())
        self.assertTrue(Notificacion.objects.filter(
            idDestinatario=self.comisionado, fusFolio=fus.folio, tipoEvento='PRORROGA_FUS',
        ).exists())
        self.assertFalse(Notificacion.objects.filter(
            idDestinatario=self.rol1, tipoEvento='PRORROGA_FUS',
        ).exists())

    def test_prorroga_exige_fecha_posterior_y_motivo(self):
        from datetime import timedelta

        from django.utils import timezone

        limite = timezone.now() + timedelta(days=3)
        fus = self._fus('ANAM/PARTICULAR/FUS/0804/2026', limite)
        self.client.force_authenticate(user=self.rol1)
        url = f'/api/fus/{fus.id}/prorroga/'

        anterior = self.client.post(
            url, {'fechaLimite': (limite - timedelta(hours=1)).isoformat(), 'motivo': 'x'}, format='json',
        )
        sin_motivo = self.client.post(
            url, {'fechaLimite': (limite + timedelta(days=1)).isoformat(), 'motivo': '  '}, format='json',
        )

        self.assertEqual(anterior.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(sin_motivo.status_code, status.HTTP_400_BAD_REQUEST)
        fus.refresh_from_db()
        self.assertAlmostEqual(fus.fechaLimite, limite, delta=timedelta(seconds=1))

    def test_prorroga_solo_para_el_dueno_del_fus(self):
        from datetime import timedelta

        from django.utils import timezone

        fus = self._fus('ANAM/PARTICULAR/FUS/0805/2026', timezone.now() - timedelta(days=1))
        nueva = (timezone.now() + timedelta(days=2)).isoformat()

        self.client.force_authenticate(user=self.otro_rol1)
        r_ajeno = self.client.post(f'/api/fus/{fus.id}/prorroga/', {'fechaLimite': nueva, 'motivo': 'x'}, format='json')
        self.client.force_authenticate(user=self.comisionado)
        r_comi = self.client.post(f'/api/fus/{fus.id}/prorroga/', {'fechaLimite': nueva, 'motivo': 'x'}, format='json')

        self.assertEqual(r_ajeno.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(r_comi.status_code, status.HTTP_403_FORBIDDEN)

    def test_tras_prorroga_si_vuelve_a_vencer_se_avisa_de_nuevo(self):
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        fus = self._fus('ANAM/PARTICULAR/FUS/0806/2026', timezone.now() - timedelta(days=2))
        call_command('revisar_sla')
        # Simula el paso del tiempo: el primer aviso ocurrió hace 3 días, se dio
        # una prórroga de 1 día (límite hace 2 días + 1 = ayer) y ya volvió a vencer.
        Notificacion.objects.filter(fusFolio=fus.folio).update(fechaGeneracion=timezone.now() - timedelta(days=3))
        FUS.objects.filter(pk=fus.pk).update(fechaLimite=timezone.now() - timedelta(days=1))
        call_command('revisar_sla')

        self.assertEqual(
            Notificacion.objects.filter(
                idDestinatario=self.rol1, fusFolio=fus.folio, tipoEvento='SLA_VENCIDO',
            ).count(), 2,
        )


class ActividadVencidoTests(APITestCase):
    """ActividadSerializer.vencido — solo los límites (tipo 'limite') ya pasados."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='En_seguimiento', defaults={'nombre': 'En seguimiento', 'tipoFlujo': 'PARTICULAR', 'orden': 2},
        )
        cls.rol1 = User.objects.create_user(username='rol1v@t.mx', email='rol1v@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1v@t.mx', nombre='Rol1', rol='ROL1', activo=1)

    def _actividad(self, tipo, dias, fus=None):
        from datetime import time
        fecha = (timezone.now() + timedelta(days=dias)).date()
        return Actividad.objects.create(
            titulo='x', fecha=fecha, horaInicio=time(10, 0), horaFin=time(11, 0),
            tipo=tipo, idCreador=self.rol1, idFusRelacionado=fus,
        )

    def _fus(self, folio, dias_limite):
        return FUS.objects.create(
            folio=folio, idSolicitanteInterno=self.rol1, descripcion='x', contexto='',
            estatusParticular_id='En_seguimiento', idUsuarioRegistra=self.rol1.id,
            fechaLimite=timezone.now() + timedelta(days=dias_limite),
        )

    def _vencido(self, actividad):
        from .serializers import ActividadSerializer
        return ActividadSerializer(actividad).data['vencido']

    def test_limite_con_fus_vencido(self):
        fus = self._fus('ANAM/PARTICULAR/FUS/0901/2026', -3)
        self.assertTrue(self._vencido(self._actividad('limite', -3, fus)))

    def test_limite_con_fus_vigente_no_esta_vencido(self):
        fus = self._fus('ANAM/PARTICULAR/FUS/0902/2026', 5)
        self.assertFalse(self._vencido(self._actividad('limite', 5, fus)))

    def test_limite_prorrogado_deja_de_estar_vencido(self):
        # El recordatorio sigue en su fecha vieja pero el FUS ya tiene nueva fecha límite
        fus = self._fus('ANAM/PARTICULAR/FUS/0903/2026', 4)
        self.assertFalse(self._vencido(self._actividad('limite', -3, fus)))

    def test_limite_sin_fus_pasado_esta_vencido(self):
        self.assertTrue(self._vencido(self._actividad('limite', -2)))

    def test_reunion_pasada_no_esta_vencida(self):
        self.assertFalse(self._vencido(self._actividad('reunion', -2)))


class WebPushTests(APITestCase):
    """Suscripción Web Push (PushSubscription) + envío real disparado desde
    push_notificacion (services/notificaciones.py) — VapidPublicKeyView,
    PushSuscribirView, PushDesuscribirView y _enviar_web_push."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='wp@t.mx', email='wp@t.mx', password='x')
        CorreoAutorizado.objects.create(email='wp@t.mx', nombre='WP', rol='ROL1', activo=1)

    def test_vapid_public_key_no_requiere_autenticacion(self):
        resp = self.client.get('/api/push/vapid-public-key/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('publicKey', resp.data)

    def test_suscribir_guarda_la_suscripcion(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/push/suscribir/', {
            'endpoint': 'https://fcm.googleapis.com/fcm/send/abc123',
            'keys': {'p256dh': 'clave-p256dh', 'auth': 'clave-auth'},
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertTrue(
            PushSubscription.objects.filter(
                idUsuario=self.user, endpoint='https://fcm.googleapis.com/fcm/send/abc123',
            ).exists()
        )

    def test_suscribir_incompleta_falla(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/push/suscribir/', {'keys': {'p256dh': 'x', 'auth': 'y'}}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_desuscribir_borra_la_suscripcion(self):
        PushSubscription.objects.create(idUsuario=self.user, endpoint='https://x.test/1', p256dh='a', auth='b')
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/push/desuscribir/', {'endpoint': 'https://x.test/1'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            PushSubscription.objects.filter(idUsuario=self.user, endpoint='https://x.test/1').exists()
        )

    @patch('pywebpush.webpush')
    def test_enviar_web_push_llama_a_webpush_por_cada_suscripcion(self, mock_webpush):
        from solicitudes.services import notificaciones as notif_mod

        sub = PushSubscription.objects.create(
            idUsuario=self.user, endpoint='https://fcm.googleapis.com/fcm/send/xyz',
            p256dh='clave-p256dh', auth='clave-auth',
        )
        notif = Notificacion.objects.create(
            idDestinatario=self.user, fusFolio='ANAM/PARTICULAR/FUS/0800/2026',
            tipoEvento='RESPUESTA', mensaje='Prueba de push.',
        )

        # connections.close_all() se mockea por la misma razón que en
        # NotificarPorCorreoTests: _enviar_web_push lo llama en su finally
        # (correcto en un hilo/worker real), pero aquí corre en el mismo
        # hilo/conexión del test — cerrarla de verdad rompería la
        # transacción compartida que usa TestCase para los demás tests.
        with patch.object(notif_mod.connections, 'close_all'):
            notif_mod._enviar_web_push(notif.id)

        mock_webpush.assert_called_once()
        _, kwargs = mock_webpush.call_args
        self.assertEqual(kwargs['subscription_info']['endpoint'], sub.endpoint)
        self.assertEqual(kwargs['subscription_info']['keys'], {'p256dh': 'clave-p256dh', 'auth': 'clave-auth'})

    @patch('pywebpush.webpush')
    def test_enviar_web_push_borra_suscripcion_vencida(self, mock_webpush):
        from pywebpush import WebPushException

        from solicitudes.services import notificaciones as notif_mod

        sub = PushSubscription.objects.create(
            idUsuario=self.user, endpoint='https://fcm.googleapis.com/fcm/send/vencida',
            p256dh='a', auth='b',
        )
        resp_410 = MagicMock(status_code=410)
        mock_webpush.side_effect = WebPushException('gone', response=resp_410)

        notif = Notificacion.objects.create(
            idDestinatario=self.user, fusFolio='ANAM/PARTICULAR/FUS/0801/2026',
            tipoEvento='RESPUESTA', mensaje='Prueba de push.',
        )
        with patch.object(notif_mod.connections, 'close_all'):
            notif_mod._enviar_web_push(notif.id)

        self.assertFalse(PushSubscription.objects.filter(pk=sub.pk).exists())


class _FixtureRolesFUS(APITestCase):
    """Base con un FUS y un usuario por cada combinación autorizado/ajeno de
    los 4 roles que pueden llegar a DescargarEvidenciaView/FUSTrazabilidadView
    — reusada por ambas suites para no duplicar el armado de datos."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)

        cls.rol1 = User.objects.create_user(username='rol1@t.mx', email='rol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1@t.mx', nombre='Rol1', rol='ROL1', activo=1)

        cls.otro_rol1 = User.objects.create_user(username='otrorol1@t.mx', email='otrorol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='otrorol1@t.mx', nombre='OtroRol1', rol='ROL1', activo=1)

        # EQUIPO_PARTICULAR autorizado: idUsuarioRegistra apunta al dueño real del FUS.
        cls.equipo_de_rol1 = User.objects.create_user(username='equipo@t.mx', email='equipo@t.mx', password='x')
        CorreoAutorizado.objects.create(
            email='equipo@t.mx', nombre='Equipo', rol='EQUIPO_PARTICULAR', activo=1,
            idUsuarioRegistra=cls.rol1.id,
        )
        # EQUIPO_PARTICULAR ajeno: asiste a otro_rol1, no al dueño del FUS de prueba.
        cls.equipo_ajeno = User.objects.create_user(username='equipoajeno@t.mx', email='equipoajeno@t.mx', password='x')
        CorreoAutorizado.objects.create(
            email='equipoajeno@t.mx', nombre='EquipoAjeno', rol='EQUIPO_PARTICULAR', activo=1,
            idUsuarioRegistra=cls.otro_rol1.id,
        )

        cls.rol2_destinatario = User.objects.create_user(username='rol2dest@t.mx', email='rol2dest@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol2dest@t.mx', nombre='Rol2Dest', rol='ROL2', activo=1)

        cls.rol2_ajeno = User.objects.create_user(username='rol2ajeno@t.mx', email='rol2ajeno@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol2ajeno@t.mx', nombre='Rol2Ajeno', rol='ROL2', activo=1)

        cls.comisionado_asignado = User.objects.create_user(username='comi@t.mx', email='comi@t.mx', password='x')
        CorreoAutorizado.objects.create(email='comi@t.mx', nombre='Comi', rol='COMISIONADO', activo=1)

        cls.comisionado_ajeno = User.objects.create_user(username='comiajeno@t.mx', email='comiajeno@t.mx', password='x')
        CorreoAutorizado.objects.create(email='comiajeno@t.mx', nombre='ComiAjeno', rol='COMISIONADO', activo=1)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0100/2026',
            idSolicitanteInterno=cls.rol1,
            descripcion='Solicitud de prueba', contexto='',
            estatusParticular_id='Registrado',
            idUsuarioRegistra=cls.rol1.id,
            idComisionado=cls.comisionado_asignado,
        )
        Turnado.objects.create(
            idFus=cls.fus, idRemitente=cls.rol1, idDestinatario=cls.rol2_destinatario,
            idMedio=cls.medio, estatusTitular_id='Recibido', activo=1,
        )


class DescargarEvidenciaViewTests(_FixtureRolesFUS):
    """ROL1 ve cualquier evidencia; EQUIPO_PARTICULAR solo la de su ROL1
    asociado; ROL2 solo si tiene un Turnado activo dirigido a él; COMISIONADO
    solo si el FUS le está asignado. Cualquier otro caso debe ser 404 (nunca
    403, para no confirmar que el recurso existe) — y la ruta resuelta del
    archivo nunca debe poder salirse de MEDIA_ROOT."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tmp_media = tempfile.mkdtemp()
        ruta_rel = os.path.join('evidencias', 'test', 'archivo.txt')
        ruta_abs = os.path.join(cls.tmp_media, ruta_rel)
        os.makedirs(os.path.dirname(ruta_abs), exist_ok=True)
        with open(ruta_abs, 'wb') as f:
            f.write(b'contenido de prueba')

        cls.evidencia = Evidencia.objects.create(
            idFus=cls.fus, nombreArchivo='archivo.txt', rutaArchivo=ruta_rel,
            tipoMime='text/plain', idUsuarioRegistra=cls.rol1.id,
        )

    def _get(self, user, evidencia=None):
        evidencia = evidencia or self.evidencia
        with override_settings(MEDIA_ROOT=self.tmp_media):
            self.client.force_authenticate(user=user)
            return self.client.get(f'/api/evidencias/{evidencia.id}/descargar/')

    def test_rol1_ve_cualquier_evidencia(self):
        self.assertEqual(self._get(self.rol1).status_code, status.HTTP_200_OK)

    def test_equipo_particular_de_ese_rol1_autorizado(self):
        self.assertEqual(self._get(self.equipo_de_rol1).status_code, status.HTTP_200_OK)

    def test_equipo_particular_ajeno_404(self):
        self.assertEqual(self._get(self.equipo_ajeno).status_code, status.HTTP_404_NOT_FOUND)

    def test_rol2_destinatario_autorizado(self):
        self.assertEqual(self._get(self.rol2_destinatario).status_code, status.HTTP_200_OK)

    def test_rol2_ajeno_404(self):
        self.assertEqual(self._get(self.rol2_ajeno).status_code, status.HTTP_404_NOT_FOUND)

    def test_comisionado_asignado_autorizado(self):
        self.assertEqual(self._get(self.comisionado_asignado).status_code, status.HTTP_200_OK)

    def test_comisionado_no_asignado_404(self):
        self.assertEqual(self._get(self.comisionado_ajeno).status_code, status.HTTP_404_NOT_FOUND)

    def test_ruta_fuera_de_media_root_devuelve_404(self):
        # rutaArchivo corrupta/manipulada que intenta escapar de MEDIA_ROOT —
        # aunque el usuario esté autorizado a ver el FUS, el archivo no se sirve.
        evidencia_maliciosa = Evidencia.objects.create(
            idFus=self.fus, nombreArchivo='fuera.txt',
            rutaArchivo=os.path.join('..', '..', 'etc', 'passwd'),
            tipoMime='text/plain', idUsuarioRegistra=self.rol1.id,
        )
        resp = self._get(self.rol1, evidencia=evidencia_maliciosa)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class FUSTrazabilidadViewTests(_FixtureRolesFUS):
    """Mismas reglas de acceso que DescargarEvidenciaView: un usuario sin
    relación con el FUS debe recibir 404 antes de que se calcule/devuelva
    cualquier evento de la línea de tiempo."""

    def _get(self, user):
        self.client.force_authenticate(user=user)
        return self.client.get(f'/api/fus/trazabilidad/{self.fus.folio}/')

    def test_rol1_ve_cualquier_fus(self):
        self.assertEqual(self._get(self.rol1).status_code, status.HTTP_200_OK)

    def test_equipo_particular_de_ese_rol1_autorizado(self):
        self.assertEqual(self._get(self.equipo_de_rol1).status_code, status.HTTP_200_OK)

    def test_equipo_particular_ajeno_404(self):
        self.assertEqual(self._get(self.equipo_ajeno).status_code, status.HTTP_404_NOT_FOUND)

    def test_rol2_destinatario_autorizado(self):
        self.assertEqual(self._get(self.rol2_destinatario).status_code, status.HTTP_200_OK)

    def test_rol2_ajeno_404(self):
        self.assertEqual(self._get(self.rol2_ajeno).status_code, status.HTTP_404_NOT_FOUND)

    def test_comisionado_asignado_autorizado(self):
        self.assertEqual(self._get(self.comisionado_asignado).status_code, status.HTTP_200_OK)

    def test_comisionado_no_asignado_404(self):
        self.assertEqual(self._get(self.comisionado_ajeno).status_code, status.HTTP_404_NOT_FOUND)


class FUSDetalleAuditoriaViewTests(_FixtureRolesFUS):
    """El modal de detalle respeta la relación del usuario con el FUS."""

    def _get(self, user):
        self.client.force_authenticate(user=user)
        return self.client.get(f'/api/fus/detalle-auditoria/{self.fus.folio}/')

    def test_rol2_destinatario_puede_ver_detalle(self):
        response = self._get(self.rol2_destinatario)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['folio'], self.fus.folio)

    def test_rol2_ajeno_no_puede_ver_detalle(self):
        self.assertEqual(
            self._get(self.rol2_ajeno).status_code,
            status.HTTP_404_NOT_FOUND,
        )


class ValidacionPorPersonaTurnadoTests(APITestCase):
    """FUS turnado a varias personas (sin comisionado): cada Titular avanza
    su propio turnado (responder -> marcar atendido) de forma independiente,
    y el Particular rechaza/concluye la parte de UNA persona sin afectar a
    las demás — el FUS solo pasa a 'Concluido' cuando TODOS los turnados
    activos ya están concluidos."""

    @classmethod
    def setUpTestData(cls):
        for clave in ('Turnado', 'En_seguimiento', 'Atendido', 'Pendiente_validacion', 'Concluido', 'Rechazado'):
            Estatus.objects.get_or_create(
                clave=clave, defaults={'nombre': clave, 'tipoFlujo': 'PARTICULAR', 'orden': 1},
            )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)

        cls.rol1 = User.objects.create_user(username='rol1@t.mx', email='rol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1@t.mx', nombre='Rol1', rol='ROL1', activo=1)

        cls.mariana = User.objects.create_user(username='mariana@t.mx', email='mariana@t.mx', password='x')
        CorreoAutorizado.objects.create(email='mariana@t.mx', nombre='Mariana', rol='ROL2', activo=1)

        cls.lucia = User.objects.create_user(username='lucia@t.mx', email='lucia@t.mx', password='x')
        CorreoAutorizado.objects.create(email='lucia@t.mx', nombre='Lucía', rol='ROL2', activo=1)

        cls.fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0200/2026',
            idSolicitanteInterno=cls.rol1,
            descripcion='Solicitud turnada a dos personas', contexto='',
            estatusParticular_id='Turnado',
            idUsuarioRegistra=cls.rol1.id,
        )
        cls.t_mariana = Turnado.objects.create(
            idFus=cls.fus, idRemitente=cls.rol1, idDestinatario=cls.mariana,
            idMedio=cls.medio, estatusTitular_id='Recibido', activo=1,
        )
        cls.t_lucia = Turnado.objects.create(
            idFus=cls.fus, idRemitente=cls.rol1, idDestinatario=cls.lucia,
            idMedio=cls.medio, estatusTitular_id='Recibido', activo=1,
        )

    def _responder(self, user, turnado):
        self.client.force_authenticate(user=user)
        return self.client.post(
            f'/api/turnados/{turnado.id}/seguimientos/',
            {'descripcionActividad': 'Reviso el caso', 'accionTexto': ''},
        )

    def _atendido(self, user, turnado):
        self.client.force_authenticate(user=user)
        return self.client.post(f'/api/turnados/{turnado.id}/atendido/')

    def _concluir_persona(self, user, turnado):
        self.client.force_authenticate(user=user)
        return self.client.post(f'/api/turnados/{turnado.id}/concluir-persona/')

    def _rechazar_persona(self, user, turnado, motivo='No es suficiente'):
        self.client.force_authenticate(user=user)
        return self.client.post(f'/api/turnados/{turnado.id}/rechazar-persona/', {'motivo': motivo})

    def test_atendido_solo_afecta_su_propio_turnado(self):
        self._responder(self.mariana, self.t_mariana)
        resp = self._atendido(self.mariana, self.t_mariana)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.t_mariana.refresh_from_db()
        self.t_lucia.refresh_from_db()
        self.fus.refresh_from_db()
        self.assertEqual(self.t_mariana.estatusTitular_id, 'Pendiente_validacion')
        self.assertEqual(self.t_lucia.estatusTitular_id, 'Recibido')  # sin tocar
        self.assertEqual(self.fus.estatusParticular_id, 'Atendido')

    def test_rol2_no_puede_marcar_atendido_sin_responder_antes(self):
        resp = self._atendido(self.mariana, self.t_mariana)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rol2_ajeno_no_puede_marcar_atendido_de_otro_turnado(self):
        self._responder(self.mariana, self.t_mariana)
        resp = self._atendido(self.lucia, self.t_mariana)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_rol1_no_puede_concluir_antes_de_atendido(self):
        self._responder(self.mariana, self.t_mariana)
        resp = self._concluir_persona(self.rol1, self.t_mariana)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rol2_no_puede_concluir_la_parte_de_otra_persona(self):
        self._responder(self.mariana, self.t_mariana)
        self._atendido(self.mariana, self.t_mariana)
        resp = self._concluir_persona(self.mariana, self.t_mariana)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_fus_sigue_atendido_hasta_que_todas_las_personas_concluyen(self):
        # Mariana responde, marca atendido, Rol 1 la concluye — Lucía sigue pendiente.
        self._responder(self.mariana, self.t_mariana)
        self._atendido(self.mariana, self.t_mariana)
        resp = self._concluir_persona(self.rol1, self.t_mariana)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.t_mariana.refresh_from_db()
        self.fus.refresh_from_db()
        self.assertEqual(self.t_mariana.estatusTitular_id, 'Concluido')
        self.assertEqual(self.fus.estatusParticular_id, 'Atendido')  # todavía no, falta Lucía

        # Lucía responde, marca atendido, Rol 1 la concluye -> ahora sí el FUS completo
        self._responder(self.lucia, self.t_lucia)
        self._atendido(self.lucia, self.t_lucia)
        resp = self._concluir_persona(self.rol1, self.t_lucia)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.t_lucia.refresh_from_db()
        self.fus.refresh_from_db()
        self.assertEqual(self.t_lucia.estatusTitular_id, 'Concluido')
        self.assertEqual(self.fus.estatusParticular_id, 'Concluido')
        self.assertIsNotNone(self.fus.fechaConclusion)

    def test_rechazar_persona_solo_afecta_su_propio_turnado(self):
        self._responder(self.mariana, self.t_mariana)
        self._atendido(self.mariana, self.t_mariana)
        resp = self._rechazar_persona(self.rol1, self.t_mariana, motivo='Falta información')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.t_mariana.refresh_from_db()
        self.t_lucia.refresh_from_db()
        self.fus.refresh_from_db()
        self.assertEqual(self.t_mariana.estatusTitular_id, 'Rechazado')
        self.assertEqual(self.t_lucia.estatusTitular_id, 'Recibido')       # ajena, sin tocar
        self.assertEqual(self.fus.estatusParticular_id, 'Atendido')        # el FUS no se rechaza completo

    def test_rechazar_persona_requiere_motivo(self):
        self._responder(self.mariana, self.t_mariana)
        self._atendido(self.mariana, self.t_mariana)
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.post(f'/api/turnados/{self.t_mariana.id}/rechazar-persona/', {'motivo': '  '})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rol2_ajeno_no_puede_validar(self):
        self._responder(self.mariana, self.t_mariana)
        self._atendido(self.mariana, self.t_mariana)
        resp = self._concluir_persona(self.lucia, self.t_mariana)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class MensajeNotificacionSegunNumeroTurnadosTests(APITestCase):
    """MarcarTurnadoAtendidoView / ConcluirPersonaTurnadoView — el mensaje de
    la notificación evita decir "tu/su parte" cuando el FUS solo tiene un
    Titular turnado: ahí esa persona ES todo el FUS, no "una parte" de él."""

    @classmethod
    def setUpTestData(cls):
        for clave in ('Turnado', 'En_seguimiento', 'Atendido', 'Pendiente_validacion', 'Concluido'):
            Estatus.objects.get_or_create(
                clave=clave, defaults={'nombre': clave, 'tipoFlujo': 'PARTICULAR', 'orden': 1},
            )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='rol1m@t.mx', email='rol1m@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1m@t.mx', nombre='Rol1', rol='ROL1', activo=1)

    def _crear_fus_con_turnados(self, folio, emails):
        fus = FUS.objects.create(
            folio=folio, idSolicitanteInterno=self.rol1,
            descripcion='x', contexto='', estatusParticular_id='Turnado',
            idUsuarioRegistra=self.rol1.id,
        )
        turnados = []
        for email in emails:
            u = User.objects.create_user(username=email, email=email, password='x')
            CorreoAutorizado.objects.create(email=email, nombre=email.split('@')[0], rol='ROL2', activo=1)
            turnados.append(Turnado.objects.create(
                idFus=fus, idRemitente=self.rol1, idDestinatario=u,
                idMedio=self.medio, estatusTitular_id='Recibido', activo=1,
            ))
        return fus, turnados

    def test_mensaje_atendido_un_solo_turnado(self):
        fus, [t] = self._crear_fus_con_turnados('ANAM/PARTICULAR/FUS/0300/2026', ['solo1@t.mx'])
        self.client.force_authenticate(user=t.idDestinatario)
        self.client.post(f'/api/turnados/{t.id}/seguimientos/', {'descripcionActividad': 'Reviso', 'accionTexto': ''})
        resp = self.client.post(f'/api/turnados/{t.id}/atendido/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertTrue(resp.data['esUnicoTurnado'])

        notif = Notificacion.objects.filter(fusFolio=fus.folio, tipoEvento='SEGUIMIENTO_FINALIZADO').first()
        self.assertIsNotNone(notif)
        self.assertNotIn('parte', notif.mensaje)
        self.assertIn('envió para validación el FUS', notif.mensaje)

    def test_mensaje_atendido_varios_turnados(self):
        fus, [t1, _t2] = self._crear_fus_con_turnados('ANAM/PARTICULAR/FUS/0301/2026', ['multi1@t.mx', 'multi2@t.mx'])
        self.client.force_authenticate(user=t1.idDestinatario)
        self.client.post(f'/api/turnados/{t1.id}/seguimientos/', {'descripcionActividad': 'Reviso', 'accionTexto': ''})
        resp = self.client.post(f'/api/turnados/{t1.id}/atendido/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertFalse(resp.data['esUnicoTurnado'])

        notif = Notificacion.objects.filter(fusFolio=fus.folio, tipoEvento='SEGUIMIENTO_FINALIZADO').first()
        self.assertIsNotNone(notif)
        self.assertIn('su parte', notif.mensaje)

    def test_mensaje_concluir_persona_un_solo_turnado(self):
        fus, [t] = self._crear_fus_con_turnados('ANAM/PARTICULAR/FUS/0302/2026', ['solo2@t.mx'])
        self.client.force_authenticate(user=t.idDestinatario)
        self.client.post(f'/api/turnados/{t.id}/seguimientos/', {'descripcionActividad': 'Reviso', 'accionTexto': ''})
        self.client.post(f'/api/turnados/{t.id}/atendido/')

        self.client.force_authenticate(user=self.rol1)
        resp = self.client.post(f'/api/turnados/{t.id}/concluir-persona/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        notif = Notificacion.objects.filter(fusFolio=fus.folio, tipoEvento='SOLICITUD_APROBADA').first()
        self.assertIsNotNone(notif)
        self.assertNotIn('parte', notif.mensaje)
        self.assertIn('concluyó el FUS', notif.mensaje)

    def test_mensaje_concluir_persona_varios_turnados(self):
        fus, [t1, _t2] = self._crear_fus_con_turnados('ANAM/PARTICULAR/FUS/0303/2026', ['multi3@t.mx', 'multi4@t.mx'])
        self.client.force_authenticate(user=t1.idDestinatario)
        self.client.post(f'/api/turnados/{t1.id}/seguimientos/', {'descripcionActividad': 'Reviso', 'accionTexto': ''})
        self.client.post(f'/api/turnados/{t1.id}/atendido/')

        self.client.force_authenticate(user=self.rol1)
        resp = self.client.post(f'/api/turnados/{t1.id}/concluir-persona/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        notif = Notificacion.objects.filter(fusFolio=fus.folio, tipoEvento='SOLICITUD_APROBADA').first()
        self.assertIsNotNone(notif)
        self.assertIn('concluyó tu parte', notif.mensaje)


class RechazarPersonaActualizaElFUSTests(APITestCase):
    """RechazarPersonaTurnadoView — con una sola persona turnada (o cuando ya
    todas están rechazadas), rechazar su parte deja TAMBIÉN el FUS en
    'Rechazado', igual que RechazarSolicitudView; con varias personas, el
    rechazo de una sola no cambia el estatus del FUS. Incluye el comando que
    corrige los FUS que quedaron contradictorios antes de este cambio."""

    @classmethod
    def setUpTestData(cls):
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='rechrol1@t.mx', email='rechrol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rechrol1@t.mx', nombre='Rol1', rol='ROL1', activo=1)

    def _fus_con_turnados(self, n, emails, estatus_fus='Turnado', estatus_turnado='Recibido'):
        fus = FUS.objects.create(
            folio=f'ANAM/PARTICULAR/FUS/{3000 + n}/2026', idSolicitanteInterno=self.rol1,
            descripcion='x', contexto='', estatusParticular_id=estatus_fus,
            idUsuarioRegistra=self.rol1.id,
        )
        turnados = []
        for email in emails:
            u = User.objects.create_user(username=email, email=email, password='x')
            CorreoAutorizado.objects.create(email=email, nombre=email.split('@')[0], rol='ROL2', activo=1)
            turnados.append(Turnado.objects.create(
                idFus=fus, idRemitente=self.rol1, idDestinatario=u,
                idMedio=self.medio, estatusTitular_id=estatus_turnado, activo=1,
            ))
        return fus, turnados

    def _responder(self, turnado):
        self.client.force_authenticate(user=turnado.idDestinatario)
        resp = self.client.post(
            f'/api/turnados/{turnado.id}/seguimientos/', {'descripcionActividad': 'Reviso', 'accionTexto': ''},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def _atendido_y_rechazar(self, turnado):
        self._responder(turnado)
        self.client.post(f'/api/turnados/{turnado.id}/atendido/')
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.post(f'/api/turnados/{turnado.id}/rechazar-persona/', {'motivo': 'Falta información'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        return resp

    def test_un_solo_turnado_rechazado_deja_el_fus_rechazado_y_se_reabre_al_responder(self):
        fus, [t] = self._fus_con_turnados(1, ['rechsolo@t.mx'])
        resp = self._atendido_y_rechazar(t)
        self.assertEqual(resp.data['estatusParticular'], 'Rechazado')
        fus.refresh_from_db()
        self.assertEqual(fus.estatusParticular_id, 'Rechazado')

        # Una nueva respuesta del Titular lo reabre: turnado y FUS vuelven a seguimiento.
        self._responder(t)
        fus.refresh_from_db()
        t.refresh_from_db()
        self.assertEqual(fus.estatusParticular_id, 'Atendido')
        self.assertEqual(t.estatusTitular_id, 'En_seguimiento')

    def test_varios_turnados_el_rechazo_de_uno_no_cambia_el_fus(self):
        fus, [t1, _t2] = self._fus_con_turnados(2, ['rechmulti1@t.mx', 'rechmulti2@t.mx'])
        self._atendido_y_rechazar(t1)
        fus.refresh_from_db()
        self.assertEqual(fus.estatusParticular_id, 'Atendido')

    def test_comando_corrige_fus_con_todos_sus_turnados_rechazados(self):
        # Estado que dejaba el rechazo anterior: FUS 'Pendiente_validacion'
        # con su única persona ya 'Rechazado'.
        contradictorio, _ = self._fus_con_turnados(
            3, ['rechcmd1@t.mx'], estatus_fus='Pendiente_validacion', estatus_turnado='Rechazado',
        )
        # Controles: varios turnados con uno solo rechazado, y uno ya correcto.
        multi, _ = self._fus_con_turnados(4, ['rechcmd2@t.mx', 'rechcmd3@t.mx'], estatus_fus='Atendido')
        primero = Turnado.objects.filter(idFus=multi).first()
        Turnado.objects.filter(pk=primero.pk).update(estatusTitular_id='Rechazado')
        correcto, _ = self._fus_con_turnados(5, ['rechcmd4@t.mx'], estatus_fus='Rechazado', estatus_turnado='Rechazado')

        call_command('reconciliar_estatus_fus', stdout=StringIO())  # simulación: no guarda
        contradictorio.refresh_from_db()
        self.assertEqual(contradictorio.estatusParticular_id, 'Pendiente_validacion')

        salida = StringIO()
        call_command('reconciliar_estatus_fus', '--aplicar', stdout=salida)
        for fus, esperado in ((contradictorio, 'Rechazado'), (multi, 'Atendido'), (correcto, 'Rechazado')):
            fus.refresh_from_db()
            self.assertEqual(fus.estatusParticular_id, esperado, fus.folio)
        self.assertIn('1 FUS corregido', salida.getvalue())

        # Idempotente: una segunda corrida ya no encuentra nada.
        salida = StringIO()
        call_command('reconciliar_estatus_fus', '--aplicar', stdout=salida)
        self.assertIn('Nada que corregir', salida.getvalue())


class BusquedaFUSFulltextTests(APITransactionTestCase):
    """FUSListCreateView.get(search=...) — migración 0033: MATCH()...AGAINST()
    IN BOOLEAN MODE sobre FUS.descripcion/contexto, Evidencia.nombreArchivo/
    comentarios y Turnado.solicitudTexto, con respaldo a icontains para
    términos más cortos que innodb_ft_min_token_size.

    APITransactionTestCase (no APITestCase): InnoDB solo refleja filas
    nuevas en el índice FULLTEXT después de un COMMIT real — con
    APITestCase (que envuelve cada test en una transacción que hace
    rollback al final) MATCH() nunca ve los datos de setUp, aunque
    icontains sí los vería vía MVCC dentro de esa misma transacción."""

    def setUp(self):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        Estatus.objects.get_or_create(
            clave='Turnado', defaults={'nombre': 'Turnado', 'tipoFlujo': 'PARTICULAR', 'orden': 2},
        )
        Estatus.objects.get_or_create(
            clave='Recibido', defaults={'nombre': 'Recibido', 'tipoFlujo': 'TITULAR', 'orden': 1},
        )
        self.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        self.rol1 = User.objects.create_user(username='rol1@t.mx', email='rol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol1@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        self.rol2 = User.objects.create_user(username='rol2@t.mx', email='rol2@t.mx', password='x')
        CorreoAutorizado.objects.create(email='rol2@t.mx', nombre='Rol2', rol='ROL2', activo=1)

        self.fus_descripcion = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0200/2026', idSolicitanteInterno=self.rol1,
            descripcion='Solicitud sobre credenciales de acceso institucional', contexto='',
            estatusParticular_id='Registrado', idUsuarioRegistra=self.rol1.id,
        )
        self.fus_evidencia = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0201/2026', idSolicitanteInterno=self.rol1,
            descripcion='Otro asunto sin relación', contexto='',
            estatusParticular_id='Registrado', idUsuarioRegistra=self.rol1.id,
        )
        Evidencia.objects.create(
            idFus=self.fus_evidencia, nombreArchivo='comprobante_pago.pdf',
            comentarios='Incluye el recibo de pago correspondiente', activo=1,
        )
        self.fus_turnado = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0202/2026', idSolicitanteInterno=self.rol1,
            descripcion='Asunto distinto', contexto='',
            estatusParticular_id='Turnado', idUsuarioRegistra=self.rol1.id,
        )
        Turnado.objects.create(
            idFus=self.fus_turnado, idRemitente=self.rol1, idDestinatario=self.rol2,
            idMedio=self.medio, estatusTitular_id='Recibido', activo=1,
            solicitudTexto='Favor de atender la revisión aduanera solicitada',
        )

    def _buscar(self, termino):
        self.client.force_authenticate(user=self.rol1)
        resp = self.client.get('/api/fus/', {'search': termino})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        return {f['folio'] for f in resp.data['results']}

    def test_encuentra_por_descripcion(self):
        self.assertIn(self.fus_descripcion.folio, self._buscar('credenciales'))

    def test_encuentra_por_evidencia(self):
        self.assertIn(self.fus_evidencia.folio, self._buscar('comprobante'))

    def test_encuentra_por_turnado(self):
        self.assertIn(self.fus_turnado.folio, self._buscar('aduanera'))

    def test_termino_corto_usa_respaldo_icontains(self):
        # 'de' tiene 2 caracteres — más corto que innodb_ft_min_token_size,
        # así que no debe usar MATCH() (no encontraría nada) sino icontains.
        folios = self._buscar('de')
        self.assertIn(self.fus_descripcion.folio, folios)

    def test_termino_sin_coincidencias_no_falla(self):
        self.assertEqual(self._buscar('xyznoexisteenningunlado'), set())

    def test_caracteres_de_operador_booleano_no_rompen_la_busqueda(self):
        # +, -, *, ", (, ) tienen significado especial en modo booleano de
        # MySQL — deben limpiarse antes de armar el término, no llegar
        # crudos a MATCH()...AGAINST() (que fallaría con sintaxis inválida).
        folios = self._buscar('+credenciales* -"acceso"')
        self.assertIn(self.fus_descripcion.folio, folios)


class NotificarPorCorreoTests(APITestCase):
    """notificar_por_correo() — Bloque L: con RQ_QUEUES configurado (Redis
    disponible) encola el envío con reintento automático (django-rq); sin
    Redis cae al hilo suelto de respaldo — mismo criterio condicional que
    CHANNEL_LAYERS/CACHES en settings.py. No hay Redis real en este entorno
    de pruebas, así que la ruta con cola se verifica mockeando
    django_rq.get_queue en vez de correr un worker de verdad."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.user = User.objects.create_user(username='dest@t.mx', email='dest@t.mx', password='x')
        cls.otro_user = User.objects.create_user(username='dest2@t.mx', email='dest2@t.mx', password='x')

    def _crear_notificacion(self):
        return Notificacion.objects.create(
            idDestinatario=self.user, fusFolio='', tipoEvento='ACTIVIDAD', mensaje='prueba',
        )

    def test_sin_rq_usa_hilo_de_respaldo(self):
        from solicitudes.services.notificaciones import notificar_por_correo
        notif = self._crear_notificacion()
        with patch('solicitudes.services.notificaciones.threading.Thread') as MockThread:
            with self.captureOnCommitCallbacks(execute=True):
                notificar_por_correo(notif)
            MockThread.assert_called_once()
            _, kwargs = MockThread.call_args
            # Se pasan ids en una lista (notificar_por_correo_lote), no el
            # objeto ni un id suelto — ver _enviar_correos_lote().
            self.assertEqual(kwargs['args'], ([notif.id],))

    @override_settings(RQ_QUEUES={'default': {'URL': 'redis://localhost:6379/0'}})
    def test_con_rq_encola_con_reintento(self):
        from solicitudes.services.notificaciones import notificar_por_correo
        notif = self._crear_notificacion()
        mock_queue = MagicMock()
        with patch('django_rq.get_queue', return_value=mock_queue):
            with self.captureOnCommitCallbacks(execute=True):
                notificar_por_correo(notif)
        mock_queue.enqueue.assert_called_once()
        args, kwargs = mock_queue.enqueue.call_args
        self.assertEqual(args[1], [notif.id])
        self.assertEqual(kwargs['retry'].max, 3)
        self.assertEqual(kwargs['retry'].intervals, [10, 30, 60])

    def test_lote_reutiliza_una_sola_consulta_al_fus(self):
        # Bloque M: turnar (u otra acción) a varios destinatarios del mismo
        # FUS debe resolver el FUS una sola vez para todo el lote, no una
        # vez por destinatario.
        from solicitudes.services import notificaciones as notif_mod

        fus = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/0300/2026', idSolicitanteInterno=self.user,
            descripcion='x', contexto='', estatusParticular_id='Registrado',
            idUsuarioRegistra=self.user.id,
        )
        n1 = Notificacion.objects.create(
            idDestinatario=self.user, fusFolio=fus.folio, tipoEvento='TURNADO', mensaje='a',
        )
        n2 = Notificacion.objects.create(
            idDestinatario=self.otro_user, fusFolio=fus.folio, tipoEvento='TURNADO', mensaje='b',
        )

        # connections.close_all() también se mockea: _enviar_correos_lote lo
        # llama en su finally (correcto en un hilo/worker real de
        # producción), pero aquí se invoca en el mismo hilo/conexión del
        # test — cerrarla de verdad rompería la transacción compartida que
        # usa TestCase para los demás tests de esta clase.
        with patch.object(
            notif_mod, '_cargar_fus_para_correo', wraps=notif_mod._cargar_fus_para_correo,
        ) as mock_cargar, patch.object(notif_mod, 'EmailMultiAlternatives') as MockEmail, \
                patch.object(notif_mod.connections, 'close_all'), \
                patch('solicitudes.views.fus.generar_pdf_fus', return_value=b'%PDF-'):
            MockEmail.return_value = MagicMock()
            notif_mod._enviar_correos_lote([n1.id, n2.id])

        mock_cargar.assert_called_once_with(fus.folio)
        self.assertEqual(MockEmail.call_count, 2)


class TodosLosChipsConsultarFUSFiltranCorrectoTests(APITestCase):
    """FUSListCreateView — verifica, uno por uno, que cada chip de Consultar
    FUS (Rol 1) devuelve exactamente el FUS que le corresponde y ninguno de
    los demás: Registrado, Turnado, Atendido ("En seguimiento"), Concluido,
    Pendiente_validacion ("Por validar"), Vencido, Por vencer, combinación de
    varios chips a la vez (OR) y Prioridad."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.rol1 = User.objects.create_user(username='chipsrol1@t.mx', email='chipsrol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='chipsrol1@t.mx', nombre='Rol1', rol='ROL1', activo=1)

        ahora = timezone.now()

        def crear(folio, estatus, prioridad='Media', fecha_limite=None):
            return FUS.objects.create(
                folio=folio, idSolicitanteInterno=cls.rol1, descripcion='x', contexto='',
                estatusParticular_id=estatus, idUsuarioRegistra=cls.rol1.id,
                prioridad=prioridad, fechaLimite=fecha_limite,
            )

        cls.f_registrado = crear('ANAM/PARTICULAR/FUS/1000/2026', 'Registrado', prioridad='Alta')
        cls.f_turnado    = crear('ANAM/PARTICULAR/FUS/1001/2026', 'Turnado', prioridad='Media')
        cls.f_atendido   = crear('ANAM/PARTICULAR/FUS/1002/2026', 'Atendido', prioridad='Baja')
        cls.f_concluido  = crear('ANAM/PARTICULAR/FUS/1003/2026', 'Concluido')
        cls.f_validar    = crear('ANAM/PARTICULAR/FUS/1004/2026', 'Pendiente_validacion')
        cls.f_vencido    = crear('ANAM/PARTICULAR/FUS/1005/2026', 'Turnado', fecha_limite=ahora - timedelta(days=1))
        cls.f_por_vencer = crear('ANAM/PARTICULAR/FUS/1006/2026', 'Turnado', fecha_limite=ahora + timedelta(hours=5))
        # Vencido pero Concluido: la temporalidad deja de aplicar una vez cerrado.
        cls.f_concl_venc = crear('ANAM/PARTICULAR/FUS/1007/2026', 'Concluido', fecha_limite=ahora - timedelta(days=3))

    def setUp(self):
        self.client.force_authenticate(user=self.rol1)

    def _folios(self, **params):
        resp = self.client.get('/api/fus/', params)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        return {item['folio'] for item in resp.data['results']}

    def test_chip_registrado(self):
        self.assertEqual(self._folios(estatusParticular='Registrado'), {self.f_registrado.folio})

    def test_chip_turnado(self):
        # Turnado también lo tienen f_vencido y f_por_vencer (ambos en
        # estatusParticular='Turnado', solo cambia su fechaLimite).
        self.assertEqual(
            self._folios(estatusParticular='Turnado'),
            {self.f_turnado.folio, self.f_vencido.folio, self.f_por_vencer.folio},
        )

    def test_chip_atendido_en_seguimiento(self):
        self.assertEqual(self._folios(estatusParticular='Atendido'), {self.f_atendido.folio})

    def test_chip_concluido(self):
        self.assertEqual(
            self._folios(estatusParticular='Concluido'),
            {self.f_concluido.folio, self.f_concl_venc.folio},
        )

    def test_chip_por_validar(self):
        self.assertEqual(self._folios(estatusParticular='Pendiente_validacion'), {self.f_validar.folio})

    def test_chip_vencido(self):
        # f_concl_venc tiene fechaLimite vencida pero está Concluido: no cuenta.
        self.assertEqual(self._folios(plazo='Vencido'), {self.f_vencido.folio})

    def test_chip_por_vencer(self):
        self.assertEqual(self._folios(plazo='PorVencer'), {self.f_por_vencer.folio})

    def test_plazo_tambien_se_acepta_dentro_de_estatusparticular(self):
        # Enlaces viejos de los dashboards mandan Vencido/PorVencer en `filtro`.
        self.assertEqual(self._folios(estatusParticular='Vencido'), {self.f_vencido.folio})
        self.assertEqual(self._folios(estatusParticular='PorVencer'), {self.f_por_vencer.folio})

    def test_varios_chips_de_estatus_se_combinan_con_or(self):
        self.assertEqual(
            self._folios(estatusParticular='Registrado,Concluido'),
            {self.f_registrado.folio, self.f_concluido.folio, self.f_concl_venc.folio},
        )

    def test_chip_prioridad(self):
        self.assertEqual(self._folios(prioridad='Alta'), {self.f_registrado.folio})
        self.assertEqual(self._folios(prioridad='Baja'), {self.f_atendido.folio})

    def test_conteos_coinciden_con_lo_que_cada_chip_realmente_devuelve(self):
        # Con un chip de estatus activo, el conteo de CADA chip (incluidos
        # los que no están seleccionados) debe ser igual a lo que ese chip
        # devolvería si se seleccionara solo.
        resp = self.client.get('/api/fus/', {'estatusParticular': 'Registrado'})
        conteos = resp.data['conteos']
        for clave in ('Registrado', 'Turnado', 'Atendido', 'Concluido', 'Pendiente_validacion', 'Rechazado'):
            with self.subTest(clave=clave):
                self.assertEqual(conteos['estatus'][clave], len(self._folios(estatusParticular=clave)))
        # El plazo cuenta dentro del estatus elegido (Registrado), no sobre todo.
        for plazo in ('Vencido', 'PorVencer'):
            with self.subTest(plazo=plazo):
                self.assertEqual(
                    conteos['plazo'][plazo],
                    len(self._folios(estatusParticular='Registrado', plazo=plazo)),
                )

    def test_chip_rechazado(self):
        Estatus.objects.get_or_create(
            clave='Rechazado', defaults={'nombre': 'Rechazado', 'tipoFlujo': 'PARTICULAR', 'orden': 9},
        )
        rechazado = FUS.objects.create(
            folio='ANAM/PARTICULAR/FUS/1008/2026', idSolicitanteInterno=self.rol1, descripcion='x',
            contexto='', estatusParticular_id='Rechazado', idUsuarioRegistra=self.rol1.id, prioridad='Media',
        )
        self.assertEqual(self._folios(estatusParticular='Rechazado'), {rechazado.folio})
        resp = self.client.get('/api/fus/')
        self.assertEqual(resp.data['conteos']['estatus']['Rechazado'], 1)

    def test_chip_rechazado_incluye_fus_con_un_solo_turnado_rechazado(self):
        # RechazarPersonaTurnadoView solo marca el turnado como 'Rechazado':
        # el FUS conserva su estatus, pero la tarjeta (estatusVisual) lo
        # muestra "Rechazado" cuando es la única persona — el chip debe
        # encontrarlo igual. Con varias personas, el rechazo de una sola no
        # convierte al FUS en Rechazado.
        Estatus.objects.get_or_create(
            clave='Rechazado', defaults={'nombre': 'Rechazado', 'tipoFlujo': 'PARTICULAR', 'orden': 9},
        )
        rol2 = User.objects.create_user(username='chipsrol2c@t.mx', email='chipsrol2c@t.mx', password='x')
        rol2_b = User.objects.create_user(username='chipsrol2d@t.mx', email='chipsrol2d@t.mx', password='x')
        medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)

        def fus_con_turnados(folio, *estatus_titulares):
            fus = FUS.objects.create(
                folio=folio, idSolicitanteInterno=self.rol1, descripcion='x', contexto='',
                estatusParticular_id='Atendido', idUsuarioRegistra=self.rol1.id, prioridad='Media',
            )
            for destinatario, estatus in zip((rol2, rol2_b), estatus_titulares):
                Turnado.objects.create(
                    idFus=fus, idRemitente=self.rol1, idDestinatario=destinatario,
                    idMedio=medio, estatusTitular_id=estatus, activo=1,
                )
            return fus

        un_turnado = fus_con_turnados('ANAM/PARTICULAR/FUS/1009/2026', 'Rechazado')
        fus_con_turnados('ANAM/PARTICULAR/FUS/1010/2026', 'Rechazado', 'Pendiente_validacion')

        self.assertEqual(self._folios(estatusParticular='Rechazado'), {un_turnado.folio})
        resp = self.client.get('/api/fus/')
        self.assertEqual(resp.data['conteos']['estatus']['Rechazado'], 1)

    def test_orden_prioridad_alta_primero_y_luego_lo_ultimo_que_cambio(self):
        def folios():
            return [item['folio'] for item in self.client.get('/api/fus/').data['results']]

        self.assertEqual(folios()[0], self.f_registrado.folio)

        # Un FUS que no es Alta y recibe un cambio sube al inicio de su grupo,
        # pero sin pasar por encima de las prioridades Alta.
        self.f_atendido.idUsuarioModifica = self.rol1.id
        self.f_atendido.save()
        orden = folios()
        self.assertEqual(orden[0], self.f_registrado.folio)
        self.assertEqual(orden[1], self.f_atendido.folio)

        # Si el FUS Alta también cambia, sigue primero.
        self.f_registrado.save()
        self.assertEqual(folios()[0], self.f_registrado.folio)


class ChipsDeEstatusSumanElTotalTests(APITestCase):
    """Consultar FUS (Rol 1): cada FUS cae en UN solo chip de estatus (el que
    muestra su tarjeta), así que los chips suman el total. Vencido / Por vencer
    son un grupo aparte ("Plazo") que cruza los estatus y se combina con ellos.
    Los escenarios reproducen los casos que antes se contaban en dos chips."""

    @classmethod
    def setUpTestData(cls):
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='sumarol1@t.mx', email='sumarol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='sumarol1@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.rol2 = User.objects.create_user(username='sumarol2@t.mx', email='sumarol2@t.mx', password='x')
        cls.rol2_b = User.objects.create_user(username='sumarol2b@t.mx', email='sumarol2b@t.mx', password='x')

        ahora = timezone.now()
        pasado, en_cinco_horas = ahora - timedelta(days=3), ahora + timedelta(hours=5)

        def crear(n, estatus_fus, *turnados, limite=None):
            fus = FUS.objects.create(
                folio=f'ANAM/PARTICULAR/FUS/{2000 + n}/2026', idSolicitanteInterno=cls.rol1,
                descripcion='x', contexto='', estatusParticular_id=estatus_fus,
                idUsuarioRegistra=cls.rol1.id, prioridad='Media', fechaLimite=limite,
            )
            for destinatario, estatus in zip((cls.rol2, cls.rol2_b), turnados):
                Turnado.objects.create(
                    idFus=fus, idRemitente=cls.rol1, idDestinatario=destinatario,
                    idMedio=cls.medio, estatusTitular_id=estatus, activo=1,
                )
            return fus

        cls.f_registrado = crear(1, 'Registrado')
        cls.f_turnado    = crear(2, 'Turnado', 'Recibido')
        cls.f_seguim     = crear(3, 'Atendido', 'En_seguimiento', limite=pasado)
        # El FUS conserva 'Atendido' pero su única persona fue rechazada.
        cls.f_rech_turn  = crear(4, 'Atendido', 'Rechazado')
        # FUS-level 'Pendiente_validacion' con turnado ya rechazado, y vencido.
        cls.f_rech_venc  = crear(5, 'Pendiente_validacion', 'Rechazado', limite=pasado)
        # Varias personas: manda el estatus del FUS ("En seguimiento").
        cls.f_varios     = crear(6, 'Atendido', 'En_seguimiento', 'Recibido')
        # Recién comisionado, sin respuesta ni turnado: FUS.En_seguimiento.
        cls.f_comision   = crear(7, 'En_seguimiento')
        cls.f_validar    = crear(8, 'Pendiente_validacion', 'Pendiente_validacion', limite=en_cinco_horas)
        # Concluido con límite vencido: el plazo ya no aplica.
        cls.f_concluido  = crear(9, 'Concluido', 'Concluido', limite=pasado)

    def setUp(self):
        self.client.force_authenticate(user=self.rol1)

    def _get(self, **params):
        resp = self.client.get('/api/fus/', params)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        return resp.data

    def _folios(self, **params):
        return {item['folio'] for item in self._get(**params)['results']}

    def test_los_chips_de_estatus_suman_el_total(self):
        conteos = self._get()['conteos']
        self.assertEqual(
            conteos['estatus'],
            {
                'Registrado': 1, 'Turnado': 1, 'Atendido': 3, 'Pendiente_validacion': 1,
                'Rechazado': 2, 'Concluido': 1,
            },
        )
        self.assertEqual(conteos['total'], 9)
        self.assertEqual(sum(conteos['estatus'].values()), conteos['total'])

    def test_cada_fus_esta_en_el_chip_que_dice_su_tarjeta(self):
        for item in self._get()['results']:
            chip = clave_chip(item['estatusVisual'])
            with self.subTest(folio=item['folio'], chip=chip):
                self.assertIn(item['folio'], self._folios(estatusParticular=chip))

    def test_rechazado_incluye_turnado_rechazado_aunque_el_fus_tenga_otro_estatus(self):
        self.assertEqual(
            self._folios(estatusParticular='Rechazado'),
            {self.f_rech_turn.folio, self.f_rech_venc.folio},
        )
        # …y esos dos ya no se cuentan en "En seguimiento" ni en "Por validar".
        self.assertEqual(
            self._folios(estatusParticular='Atendido'),
            {self.f_seguim.folio, self.f_varios.folio, self.f_comision.folio},
        )
        self.assertEqual(self._folios(estatusParticular='Pendiente_validacion'), {self.f_validar.folio})

    def test_en_seguimiento_es_alias_de_atendido(self):
        self.assertEqual(
            self._folios(estatusParticular='En_seguimiento'),
            self._folios(estatusParticular='Atendido'),
        )

    def test_plazo_cruza_los_estatus(self):
        self.assertEqual(self._folios(plazo='Vencido'), {self.f_seguim.folio, self.f_rech_venc.folio})
        self.assertEqual(self._folios(plazo='PorVencer'), {self.f_validar.folio})

    def test_plazo_se_combina_con_el_estatus_elegido(self):
        self.assertEqual(
            self._folios(estatusParticular='Rechazado', plazo='Vencido'), {self.f_rech_venc.folio},
        )
        self.assertEqual(self._folios(estatusParticular='Concluido', plazo='Vencido'), set())

    def test_cada_grupo_cuenta_sobre_el_filtro_del_otro(self):
        # Con "Rechazado" elegido, el plazo cuenta solo dentro de los rechazados.
        conteos = self._get(estatusParticular='Rechazado')['conteos']
        self.assertEqual(conteos['plazo'], {'Vencido': 1, 'PorVencer': 0})
        # Con "Vencido" elegido, los estatus cuentan solo dentro de los vencidos
        # y siguen sumando el total.
        conteos = self._get(plazo='Vencido')['conteos']
        self.assertEqual(conteos['estatus']['Atendido'], 1)
        self.assertEqual(conteos['estatus']['Rechazado'], 1)
        self.assertEqual(conteos['total'], 2)
        self.assertEqual(sum(conteos['estatus'].values()), conteos['total'])

    def test_prioridad_por_enlace_tambien_ajusta_los_conteos(self):
        FUS.objects.filter(pk=self.f_comision.pk).update(prioridad='Alta')
        data = self._get(prioridad='Alta')
        self.assertEqual({item['folio'] for item in data['results']}, {self.f_comision.folio})
        self.assertEqual(data['conteos']['total'], 1)
        self.assertEqual(data['conteos']['estatus']['Atendido'], 1)


class TodosLosChipsSolicitudesTurnadasFiltranCorrectoTests(APITestCase):
    """MisTurnadosView — mismo objetivo que el test anterior, pero del lado
    de Rol 2: Recibido, En_seguimiento, Pendiente_validacion, Rechazado y
    Concluido (todos por Turnado.estatusTitular, el que muestra su tarjeta),
    el grupo Plazo (Vencido, Por vencer) y Prioridad (solo por enlace)."""

    @classmethod
    def setUpTestData(cls):
        Estatus.objects.get_or_create(
            clave='Registrado', defaults={'nombre': 'Registrado', 'tipoFlujo': 'PARTICULAR', 'orden': 1},
        )
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='chipsrol1b@t.mx', email='chipsrol1b@t.mx', password='x')
        CorreoAutorizado.objects.create(email='chipsrol1b@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.rol2 = User.objects.create_user(username='chipsrol2b@t.mx', email='chipsrol2b@t.mx', password='x')
        CorreoAutorizado.objects.create(email='chipsrol2b@t.mx', nombre='Rol2', rol='ROL2', activo=1)

        ahora = timezone.now()

        def crear_turnado(folio, estatus_fus, estatus_titular, prioridad='Media', fecha_limite=None):
            fus = FUS.objects.create(
                folio=folio, idSolicitanteInterno=cls.rol1, descripcion='x', contexto='',
                estatusParticular_id=estatus_fus, idUsuarioRegistra=cls.rol1.id,
                prioridad=prioridad, fechaLimite=fecha_limite,
            )
            return Turnado.objects.create(
                idFus=fus, idRemitente=cls.rol1, idDestinatario=cls.rol2,
                idMedio=cls.medio, estatusTitular_id=estatus_titular, activo=1,
            )

        cls.t_recibido    = crear_turnado('ANAM/PARTICULAR/FUS/1100/2026', 'Turnado', 'Recibido', prioridad='Alta')
        cls.t_seguimiento = crear_turnado('ANAM/PARTICULAR/FUS/1101/2026', 'En_seguimiento', 'En_seguimiento', prioridad='Baja')
        cls.t_concluido   = crear_turnado('ANAM/PARTICULAR/FUS/1102/2026', 'Concluido', 'Concluido')
        cls.t_validar     = crear_turnado('ANAM/PARTICULAR/FUS/1103/2026', 'Pendiente_validacion', 'Pendiente_validacion')
        cls.t_rechazado   = crear_turnado('ANAM/PARTICULAR/FUS/1104/2026', 'Rechazado', 'Rechazado')
        cls.t_vencido     = crear_turnado(
            'ANAM/PARTICULAR/FUS/1105/2026', 'Turnado', 'Recibido', fecha_limite=ahora - timedelta(days=1),
        )
        cls.t_por_vencer  = crear_turnado(
            'ANAM/PARTICULAR/FUS/1106/2026', 'Turnado', 'Recibido', fecha_limite=ahora + timedelta(hours=5),
        )

    def setUp(self):
        self.client.force_authenticate(user=self.rol2)

    def _folios(self, **params):
        resp = self.client.get('/api/turnados/mis-turnados/', params)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        return {item['idFus']['folio'] for item in resp.data['results']}

    def test_chip_recibido(self):
        # Recibido también lo tienen t_vencido y t_por_vencer.
        self.assertEqual(
            self._folios(estatusTitular='Recibido'),
            {self.t_recibido.idFus.folio, self.t_vencido.idFus.folio, self.t_por_vencer.idFus.folio},
        )

    def test_chip_en_seguimiento(self):
        self.assertEqual(self._folios(estatusTitular='En_seguimiento'), {self.t_seguimiento.idFus.folio})

    def test_chip_concluido(self):
        self.assertEqual(self._folios(estatusTitular='Concluido'), {self.t_concluido.idFus.folio})

    def test_chip_pendiente_validacion(self):
        self.assertEqual(self._folios(estatusTitular='Pendiente_validacion'), {self.t_validar.idFus.folio})

    def test_chip_rechazado(self):
        self.assertEqual(self._folios(estatusTitular='Rechazado'), {self.t_rechazado.idFus.folio})

    def test_chip_vencido(self):
        self.assertEqual(self._folios(plazo='Vencido'), {self.t_vencido.idFus.folio})

    def test_chip_por_vencer(self):
        self.assertEqual(self._folios(plazo='PorVencer'), {self.t_por_vencer.idFus.folio})

    def test_plazo_tambien_se_acepta_dentro_de_estatustitular(self):
        # Enlaces viejos de los dashboards mandan Vencido/PorVencer en `filtro`.
        self.assertEqual(self._folios(estatusTitular='Vencido'), {self.t_vencido.idFus.folio})
        self.assertEqual(self._folios(estatusTitular='PorVencer'), {self.t_por_vencer.idFus.folio})

    def test_chip_prioridad(self):
        self.assertEqual(self._folios(prioridad='Alta'), {self.t_recibido.idFus.folio})
        self.assertEqual(self._folios(prioridad='Baja'), {self.t_seguimiento.idFus.folio})

    def test_conteos_coinciden_con_lo_que_cada_chip_realmente_devuelve(self):
        resp = self.client.get('/api/turnados/mis-turnados/', {'estatusTitular': 'Recibido'})
        conteos = resp.data['conteos']
        for clave in ('Recibido', 'En_seguimiento', 'Concluido', 'Pendiente_validacion', 'Rechazado'):
            with self.subTest(clave=clave):
                self.assertEqual(conteos['estatus'][clave], len(self._folios(estatusTitular=clave)))
        # El plazo cuenta dentro del estatus elegido (Recibido), no sobre todo.
        for plazo in ('Vencido', 'PorVencer'):
            with self.subTest(plazo=plazo):
                self.assertEqual(
                    conteos['plazo'][plazo],
                    len(self._folios(estatusTitular='Recibido', plazo=plazo)),
                )


class ChipsDeEstatusSumanElTotalRol2Tests(APITestCase):
    """Solicitudes turnadas (Rol 2): cada turnado cae en UN solo chip de estatus
    (Turnado.estatusTitular, el que muestra su tarjeta), así que los chips suman
    el total. Vencido / Por vencer son un grupo aparte ("Plazo") que cruza los
    estatus. Cubre el caso que antes quedaba fuera de todos los chips: con
    varias personas turnadas, el rechazo/validación de UNA sola vive solo en su
    turnado (el FUS conserva su estatus)."""

    @classmethod
    def setUpTestData(cls):
        cls.medio = MedioRecepcion.objects.create(nombreMedio='Correo electrónico', paraTurnado=1)
        cls.rol1 = User.objects.create_user(username='sumar2rol1@t.mx', email='sumar2rol1@t.mx', password='x')
        CorreoAutorizado.objects.create(email='sumar2rol1@t.mx', nombre='Rol1', rol='ROL1', activo=1)
        cls.rol2 = User.objects.create_user(username='sumar2rol2@t.mx', email='sumar2rol2@t.mx', password='x')
        CorreoAutorizado.objects.create(email='sumar2rol2@t.mx', nombre='Rol2', rol='ROL2', activo=1)
        cls.colega = User.objects.create_user(username='sumar2colega@t.mx', email='sumar2colega@t.mx', password='x')
        CorreoAutorizado.objects.create(email='sumar2colega@t.mx', nombre='Colega', rol='ROL2', activo=1)

        ahora = timezone.now()
        pasado, en_cinco_horas = ahora - timedelta(days=3), ahora + timedelta(hours=5)

        def crear(n, estatus_fus, mio, colega=None, prioridad='Media', limite=None):
            fus = FUS.objects.create(
                folio=f'ANAM/PARTICULAR/FUS/{4000 + n}/2026', idSolicitanteInterno=cls.rol1,
                descripcion='x', contexto='', estatusParticular_id=estatus_fus,
                idUsuarioRegistra=cls.rol1.id, prioridad=prioridad, fechaLimite=limite,
            )
            turnado = Turnado.objects.create(
                idFus=fus, idRemitente=cls.rol1, idDestinatario=cls.rol2,
                idMedio=cls.medio, estatusTitular_id=mio, activo=1,
            )
            if colega:
                Turnado.objects.create(
                    idFus=fus, idRemitente=cls.rol1, idDestinatario=cls.colega,
                    idMedio=cls.medio, estatusTitular_id=colega, activo=1,
                )
            return turnado

        cls.t_recibido  = crear(1, 'Turnado', 'Recibido', prioridad='Alta')
        cls.t_seguim    = crear(2, 'Atendido', 'En_seguimiento', limite=pasado)
        # Varias personas: el FUS sigue 'Atendido' pero MI parte fue rechazada.
        cls.t_rech_pers = crear(3, 'Atendido', 'Rechazado', colega='En_seguimiento')
        # Varias personas: MI parte está enviada a validar; el FUS sigue 'Atendido'.
        cls.t_valid_pers = crear(4, 'Atendido', 'Pendiente_validacion', colega='En_seguimiento')
        # Rechazo del FUS completo (espejado en el turnado) y vencido.
        cls.t_rech_fus  = crear(5, 'Rechazado', 'Rechazado', limite=pasado)
        # Mi parte concluida aunque el FUS siga abierto (la otra persona pendiente),
        # con límite vencido: para MÍ el plazo ya no aplica.
        cls.t_concl_pers = crear(6, 'Atendido', 'Concluido', colega='En_seguimiento', limite=pasado)
        cls.t_validar   = crear(7, 'Pendiente_validacion', 'Pendiente_validacion', limite=en_cinco_horas)
        cls.t_concluido = crear(8, 'Concluido', 'Concluido', limite=pasado)

    def setUp(self):
        self.client.force_authenticate(user=self.rol2)

    def _get(self, **params):
        resp = self.client.get('/api/turnados/mis-turnados/', params)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        return resp.data

    def _folios(self, **params):
        return {item['idFus']['folio'] for item in self._get(**params)['results']}

    def test_los_chips_de_estatus_suman_el_total(self):
        conteos = self._get()['conteos']
        self.assertEqual(
            conteos['estatus'],
            {
                'Recibido': 1, 'En_seguimiento': 1, 'Pendiente_validacion': 2,
                'Rechazado': 2, 'Concluido': 2,
            },
        )
        self.assertEqual(conteos['total'], 8)
        self.assertEqual(sum(conteos['estatus'].values()), conteos['total'])

    def test_cada_turnado_esta_en_el_chip_que_dice_su_tarjeta(self):
        for item in self._get()['results']:
            with self.subTest(folio=item['idFus']['folio'], estatus=item['estatusTitular']):
                self.assertIn(item['idFus']['folio'], self._folios(estatusTitular=item['estatusTitular']))

    def test_rechazo_y_validacion_de_una_sola_persona_aparecen_en_su_chip(self):
        self.assertEqual(
            self._folios(estatusTitular='Rechazado'),
            {self.t_rech_pers.idFus.folio, self.t_rech_fus.idFus.folio},
        )
        self.assertEqual(
            self._folios(estatusTitular='Pendiente_validacion'),
            {self.t_valid_pers.idFus.folio, self.t_validar.idFus.folio},
        )

    def test_plazo_cruza_los_estatus_y_no_cuenta_mi_parte_concluida(self):
        self.assertEqual(self._folios(plazo='Vencido'), {self.t_seguim.idFus.folio, self.t_rech_fus.idFus.folio})
        self.assertEqual(self._folios(plazo='PorVencer'), {self.t_validar.idFus.folio})

    def test_plazo_se_combina_con_el_estatus_elegido(self):
        self.assertEqual(
            self._folios(estatusTitular='Rechazado', plazo='Vencido'), {self.t_rech_fus.idFus.folio},
        )
        self.assertEqual(self._folios(estatusTitular='Concluido', plazo='Vencido'), set())

    def test_cada_grupo_cuenta_sobre_el_filtro_del_otro(self):
        conteos = self._get(estatusTitular='Rechazado')['conteos']
        self.assertEqual(conteos['plazo'], {'Vencido': 1, 'PorVencer': 0})
        conteos = self._get(plazo='Vencido')['conteos']
        self.assertEqual(conteos['estatus']['En_seguimiento'], 1)
        self.assertEqual(conteos['estatus']['Rechazado'], 1)
        self.assertEqual(conteos['total'], 2)
        self.assertEqual(sum(conteos['estatus'].values()), conteos['total'])

    def test_orden_prioridad_alta_primero_y_luego_lo_ultimo_que_cambio(self):
        def folios():
            return [item['idFus']['folio'] for item in self._get()['results']]

        self.assertEqual(folios()[0], self.t_recibido.idFus.folio)  # la única Alta

        # Un cambio en el turnado de una no-Alta la sube al inicio de su grupo,
        # pero sin pasar por encima de las prioridades Alta.
        self.t_seguim.idUsuarioModifica = self.rol1.id
        self.t_seguim.save()
        self.assertEqual(folios()[:2], [self.t_recibido.idFus.folio, self.t_seguim.idFus.folio])

        # Y un cambio en el FUS (p. ej. una prórroga) también cuenta como cambio.
        self.t_concluido.idFus.save()
        self.assertEqual(folios()[:2], [self.t_recibido.idFus.folio, self.t_concluido.idFus.folio])
