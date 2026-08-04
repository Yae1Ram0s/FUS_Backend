import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from autenticacion.models import CorreoAutorizado
from catalogos.models import MedioRecepcion, PrioridadCriterio
from solicitudes.models import FUS
from solicitudes.services.folios import generar_folio
from .crear_fus_prueba import NOMBRES_EXTERNOS, _correo, _telefono

# Casos distintos a los de crear_fus_prueba.py (esos ya se usaron todos en el
# lote anterior) — mismo registro formal, mismo contexto de aduanas/ANAM.
CASOS_HOY = [
    ('Solicitud de información sobre el procedimiento para presentar una '
     'inconformidad respecto a una clasificación arancelaria asignada a '
     'mercancía importada.',
     'El solicitante representa a una empresa importadora de insumos '
     'electrónicos y requiere orientación antes de presentar el recurso.'),
    ('Queja por demora prolongada en la liberación de un vehículo de carga '
     'retenido para inspección aduanera sin notificación de motivo.',
     'El transportista reporta pérdidas económicas por el tiempo de espera y '
     'solicita respuesta a la brevedad.'),
    ('Solicitud de reunión informativa sobre los nuevos lineamientos para el '
     'despacho aduanero de mercancía perecedera.',
     'La cámara empresarial solicitante agrupa a productores agrícolas de '
     'exportación de la región.'),
    ('Reporte sobre presunta simulación de operación de comercio exterior '
     'detectada en un análisis de riesgo preliminar.',
     'La información proviene de un área interna y requiere validación antes '
     'de escalarse a la instancia correspondiente.'),
    ('Solicitud de constancia de no adeudo fiscal en materia aduanera para '
     'trámite ante una institución bancaria.',
     'El solicitante requiere el documento con carácter urgente por un '
     'proceso de licitación en curso.'),
    ('Consulta sobre el procedimiento para solicitar la devolución de '
     'impuestos al comercio exterior pagados en exceso.',
     'El solicitante adjunta el pedimento correspondiente y el comprobante '
     'de pago original.'),
    ('Queja por presunta falta de atención oportuna en el módulo de '
     'orientación al usuario de una aduana fronteriza.',
     'El solicitante señala haber esperado más de dos horas sin ser atendido '
     'durante su última visita.'),
    ('Solicitud de información pública sobre el padrón de agentes aduanales '
     'autorizados en una aduana específica.',
     'La solicitud la presenta un despacho jurídico con fines de debida '
     'diligencia comercial.'),
    ('Reporte de posible extravío de documentación entregada en ventanilla '
     'como parte de un trámite de importación definitiva.',
     'El solicitante conserva el acuse de recepción como respaldo del '
     'trámite realizado.'),
    ('Solicitud de prórroga para el desahogo de un requerimiento de '
     'información dentro de un procedimiento administrativo en curso.',
     'El solicitante justifica la solicitud por la complejidad de la '
     'documentación requerida.'),
    ('Consulta sobre los requisitos para operar como recinto fiscalizado '
     'para el almacenamiento temporal de mercancía de exportación.',
     'La solicitud proviene de una empresa logística con interés en ampliar '
     'sus operaciones en la región.'),
    ('Queja por presunto cobro no justificado durante un servicio de '
     'maniobras en un recinto fiscal.',
     'El solicitante adjunta el comprobante del cobro y solicita se aclare '
     'su procedencia.'),
    ('Solicitud de audiencia para exponer una propuesta de colaboración '
     'entre la agencia y una universidad en materia de comercio exterior.',
     'La propuesta busca establecer un programa de prácticas profesionales '
     'para estudiantes de la carrera de comercio internacional.'),
    ('Reporte ciudadano sobre vehículos estacionados de forma irregular en '
     'el perímetro de acceso a una aduana, con riesgo para la vialidad.',
     'El reporte lo presenta un vecino de la zona, sin relación directa con '
     'ningún trámite aduanero.'),
]


class Command(BaseCommand):
    help = (
        'Registra FUS de prueba fechados hoy, todos en estatus Registrado '
        '(sin turnar), con información variada — para probar la bandeja de '
        'recién llegados sin tocar el flujo de turnado/seguimiento.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--cantidad', type=int, default=12)

    @transaction.atomic
    def handle(self, *args, **options):
        cantidad = max(12, options['cantidad'])

        rol1 = CorreoAutorizado.objects.filter(rol='ROL1', activo=1).first()
        if not rol1:
            raise CommandError('No hay ningún usuario ROL1 activo — créalo antes de correr este comando.')
        remitente = User.objects.filter(email=rol1.email).first()
        if not remitente:
            raise CommandError(f'No existe cuenta de acceso (auth_user) para {rol1.email}.')

        medios_registro = list(MedioRecepcion.objects.filter(activo=1))
        criterios_por_nivel = {
            nivel: list(PrioridadCriterio.objects.filter(activo=1, nivel=nivel).values_list('descripcionCriterio', flat=True))
            for nivel in ('Alta', 'Media', 'Baja')
        }

        hoy = timezone.localtime(timezone.now())
        creados = 0

        for i in range(cantidad):
            caso_desc, caso_ctx = CASOS_HOY[i % len(CASOS_HOY)]

            # Repartidas a lo largo del día de hoy (horario hábil), no todas
            # al mismo minuto, para que se vean como registros independientes.
            fecha_registro = hoy.replace(
                hour=random.randint(8, 18), minute=random.randint(0, 59),
                second=random.randint(0, 59), microsecond=0,
            )
            if fecha_registro > hoy:
                fecha_registro = hoy - timezone.timedelta(minutes=random.randint(1, 120))

            prioridad = random.choices(['Alta', 'Media', 'Baja'], weights=[0.22, 0.45, 0.33])[0]
            opciones_criterio = criterios_por_nivel.get(prioridad) or []
            criterios = ' | '.join(random.sample(opciones_criterio, k=min(2, len(opciones_criterio)))) if opciones_criterio else ''

            dias_sla = {'Alta': (3, 5), 'Media': (7, 12), 'Baja': (14, 21)}[prioridad]
            fecha_limite = fecha_registro + timezone.timedelta(days=random.randint(*dias_sla))

            externo = random.choice(NOMBRES_EXTERNOS)
            medio = random.choice(medios_registro)

            fus = FUS.objects.create(
                folio=generar_folio('ROL1', fecha_registro.year),
                idSolicitanteInterno=remitente,
                fechaHora=fecha_registro,
                descripcion=caso_desc,
                contexto=caso_ctx,
                idMedioRecepcion=medio,
                medioEspecificacion='Buzón físico en módulo de atención' if medio.nombreMedio == 'Otro' else None,
                prioridad=prioridad,
                criterios=criterios,
                nombreExterno=externo,
                telefonoExterno=_telefono() if externo else None,
                correoExterno=_correo(externo) if externo else None,
                estatusParticular_id='Registrado',
                fechaLimite=fecha_limite,
                idUsuarioRegistra=remitente.id,
            )
            # fechaRegistro es auto_now_add — se corrige con un UPDATE (que sí
            # respeta el valor explícito) para repartirlas a lo largo del día.
            FUS.objects.filter(pk=fus.pk).update(
                fechaRegistro=fecha_registro, fechaModificacion=fecha_registro,
            )
            creados += 1

        self.stdout.write(self.style.SUCCESS(
            f'Se registraron {creados} FUS de hoy ({hoy.date()}), todos en estatus Registrado.'
        ))
