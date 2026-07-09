from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from autenticacion.models import CorreoAutorizado
from catalogos.models import Estatus, MedioRecepcion
from .models import FUS


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
