import os
import tempfile

from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from autenticacion.models import CorreoAutorizado
from catalogos.models import Estatus, MedioRecepcion
from .models import FUS, Evidencia, Turnado


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
        for clave in ('Turnado', 'En_seguimiento', 'Atendido', 'Concluido', 'Rechazado'):
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
        self.assertEqual(self.t_mariana.estatusTitular_id, 'Atendido')
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
