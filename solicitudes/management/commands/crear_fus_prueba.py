import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from autenticacion.models import CorreoAutorizado
from catalogos.models import MedioRecepcion, PrioridadCriterio
from solicitudes.models import FUS, Seguimiento, Turnado
from solicitudes.services.folios import generar_folio

# (descripción, contexto) — casos formales típicos de una oficina de atención
# ciudadana en una agencia de aduanas. Se reutilizan aduanas/direcciones
# reales del catálogo para que se lean como solicitudes de verdad.
CASOS = [
    ('Solicitud de información sobre el estatus de un trámite de importación temporal '
     'que permanece detenido en la aduana desde hace más de tres semanas.',
     'El solicitante indica haber presentado toda la documentación requerida y no ha '
     'recibido respuesta del área operativa correspondiente.'),
    ('Queja formal por presunto trato inadecuado de personal aduanero hacia un '
     'transportista durante una revisión de mercancía.',
     'El hecho ocurrió en el turno vespertino; el solicitante cuenta con el número '
     'de pedimento y el nombre del agente involucrado.'),
    ('Solicitud de reunión con la persona Titular para exponer afectaciones '
     'derivadas de un cambio reciente en el procedimiento de despacho aduanero.',
     'La empresa solicitante opera bajo el esquema de empresa certificada (OEA) y '
     'reporta retrasos recurrentes desde la actualización del sistema.'),
    ('Reporte ciudadano sobre posible irregularidad en el cobro de derechos '
     'aduaneros no contemplados en la tarifa vigente.',
     'Se adjuntan capturas de pantalla del comprobante de pago y del arancel '
     'consultado en el portal oficial.'),
    ('Solicitud de copia certificada de un pedimento de exportación para trámite '
     'ante una institución financiera.',
     'El solicitante requiere el documento con carácter de urgente por vencimiento '
     'de un plazo bancario.'),
    ('Consulta sobre los requisitos vigentes para la importación definitiva de '
     'maquinaria industrial usada.',
     'El solicitante es representante legal de una empresa maquiladora con '
     'operaciones en la frontera norte.'),
    ('Denuncia sobre posible triangulación de mercancía no declarada detectada '
     'durante un recorrido de verificación.',
     'La información se recibió de forma anónima a través del portal de '
     'transparencia y requiere validación por la unidad competente.'),
    ('Solicitud de prórroga para la regularización de mercancía retenida en '
     'depósito fiscal por documentación incompleta.',
     'El interesado explica que la demora se debió a trámites consulares en el '
     'país de origen de la mercancía.'),
    ('Queja por la duración excesiva de un proceso de verificación física de '
     'mercancía perecedera, con riesgo de pérdida total del embarque.',
     'El solicitante solicita atención inmediata dado el carácter perecedero de '
     'la carga retenida.'),
    ('Solicitud de información pública sobre estadísticas de recaudación aduanera '
     'de la dirección general correspondiente.',
     'La solicitud proviene de un centro de investigación académica con fines '
     'estadísticos, sin datos personales involucrados.'),
    ('Seguimiento a un expediente previo relacionado con la devolución de un '
     'depósito en garantía tras la conclusión de un trámite aduanero.',
     'El solicitante ya cuenta con folio de resolución favorable y reporta que el '
     'depósito aún no ha sido liberado.'),
    ('Solicitud de asesoría sobre el procedimiento para la donación de mercancía '
     'decomisada a una institución de beneficencia.',
     'La institución solicitante cuenta con registro vigente ante la autoridad '
     'correspondiente y adjunta la documentación de acreditación.'),
    ('Reporte sobre presunta falta administrativa cometida por un agente aduanal '
     'en el manejo de documentación de un cliente.',
     'El solicitante aporta copia del contrato de servicios y correspondencia '
     'electrónica como evidencia del hecho reportado.'),
    ('Solicitud de información sobre el estado que guarda una revisión de origen '
     'aplicada a mercancía importada bajo trato preferencial.',
     'La empresa solicitante requiere la información para efectos de una '
     'auditoría comercial interna.'),
    ('Queja por la falta de respuesta a un trámite de rectificación de pedimento '
     'presentado hace más de un mes.',
     'El solicitante señala haber acudido en tres ocasiones a la ventanilla sin '
     'obtener una respuesta definitiva.'),
    ('Solicitud de audiencia para exponer una propuesta de mejora en el proceso '
     'de atención a usuarios en el módulo de recaudación.',
     'La propuesta proviene de una cámara empresarial del sector logístico '
     'regional.'),
    ('Reporte de un posible conflicto de interés en la asignación de un servicio '
     'de verificación a un tercero autorizado.',
     'El solicitante solicita reserva de su identidad durante el trámite del '
     'reporte.'),
    ('Solicitud de información sobre los criterios utilizados para la selección '
     'de mercancía sujeta a reconocimiento aduanero.',
     'La consulta la presenta un despacho aduanal con interés en la '
     'transparencia del proceso de selección.'),
    ('Queja por cobro duplicado de una multa administrativa ya solventada con '
     'anterioridad.',
     'El solicitante adjunta el comprobante de pago original y la notificación '
     'de la multa reiterada.'),
    ('Solicitud de información sobre el trámite para la certificación como '
     'operador económico autorizado (OEA).',
     'La empresa solicitante se dedica a la exportación de productos '
     'agroindustriales.'),
    ('Reporte de daño a mercancía durante un procedimiento de verificación, con '
     'solicitud de indemnización correspondiente.',
     'El solicitante aporta fotografías del estado de la mercancía antes y '
     'después de la revisión.'),
    ('Solicitud de reunión de seguimiento para revisar el avance de un plan de '
     'trabajo conjunto entre la agencia y una asociación de transportistas.',
     'La solicitud da continuidad a una mesa de trabajo realizada el trimestre '
     'anterior.'),
    ('Consulta sobre el procedimiento aplicable para la importación temporal de '
     'equipo destinado a un evento internacional.',
     'El evento se realizará en territorio nacional y cuenta con aval de la '
     'secretaría organizadora.'),
    ('Queja por presunta solicitud indebida de pago adicional para agilizar un '
     'trámite de despacho aduanero.',
     'El solicitante conserva mensajería como evidencia y solicita que el caso '
     'se turne con carácter confidencial.'),
    ('Solicitud de información sobre el estatus de una queja presentada con '
     'anterioridad ante el órgano interno de control.',
     'El solicitante no ha recibido notificación formal sobre el resultado de la '
     'investigación correspondiente.'),
    ('Solicitud de acceso a las instalaciones de una aduana para una visita '
     'académica con fines de investigación universitaria.',
     'La solicitud proviene de una institución de educación superior con '
     'convenio vigente con la dependencia.'),
    ('Reporte de una posible falla en el sistema electrónico utilizado para el '
     'registro de pedimentos, que ha generado retrasos generalizados.',
     'Varios despachos aduanales de la misma región reportan la misma '
     'incidencia técnica.'),
    ('Solicitud de información sobre requisitos para la habilitación de un nuevo '
     'recinto fiscalizado estratégico.',
     'La solicitud la presenta un grupo inversionista interesado en operar en la '
     'región del Pacífico.'),
    ('Queja por presunta discrecionalidad en la aplicación de criterios de '
     'valoración aduanera a mercancía idéntica de distintos importadores.',
     'El solicitante adjunta pedimentos comparativos como sustento de su '
     'inconformidad.'),
    ('Solicitud de prórroga para la presentación de documentación complementaria '
     'en un procedimiento administrativo en trámite.',
     'El solicitante justifica el retraso por causas de fuerza mayor debidamente '
     'documentadas.'),
    ('Seguimiento a la entrega de mercancía liberada tras la conclusión '
     'favorable de un procedimiento de verificación de origen.',
     'El solicitante reporta que, pese a la resolución favorable, la mercancía '
     'continúa retenida en depósito.'),
    ('Solicitud de información general sobre los horarios y módulos de atención '
     'disponibles para trámites de comercio exterior.',
     'La consulta la presenta un usuario de primera vez sin trámite previo '
     'registrado.'),
]

NOMBRES_EXTERNOS = [
    'Alejandro Ruiz Betancourt', 'María Fernanda Osorio Campos', 'Ricardo Solano Mejía',
    'Patricia Elizondo Vargas', 'Jorge Iván Cabrera Soto', 'Lucía Marín Herrera',
    'Eduardo Salgado Torres', 'Claudia Ibarra Nuño', 'Francisco Javier Reyes Camacho',
    'Ana Gabriela Peña Rodríguez', 'Héctor Manuel Quintero Díaz', 'Verónica Alcántara Luna',
    'Roberto Carlos Ávila Ponce', 'Guadalupe Montes de Oca', 'Sergio Armando Cordero Ríos',
    None, None, None, None, None, None,  # algunos sin datos de contacto (trámite interno)
]

DOMINIOS_CORREO = ['gmail.com', 'hotmail.com', 'outlook.com']


def _telefono():
    return f'55{random.randint(10000000, 99999999)}'


def _correo(nombre):
    base = nombre.lower().split(' ')
    usuario = f'{base[0]}.{base[-1]}'.replace('í', 'i').replace('é', 'e').replace('á', 'a').replace('ó', 'o').replace('ú', 'u')
    return f'{usuario}@{random.choice(DOMINIOS_CORREO)}'


class Command(BaseCommand):
    help = (
        'Crea al menos 30 FUS de prueba con fechas, prioridades, medios de '
        'recepción y estatus variados, más sus turnados y respuestas, para '
        'poblar Reportes con datos realistas.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--cantidad', type=int, default=32)

    @transaction.atomic
    def handle(self, *args, **options):
        cantidad = max(30, options['cantidad'])

        rol1 = CorreoAutorizado.objects.filter(rol='ROL1', activo=1).first()
        if not rol1:
            raise CommandError('No hay ningún usuario ROL1 activo — créalo antes de correr este comando.')
        remitente = User.objects.filter(email=rol1.email).first()
        if not remitente:
            raise CommandError(f'No existe cuenta de acceso (auth_user) para {rol1.email}.')

        destinatarios = list(User.objects.filter(
            email__in=CorreoAutorizado.objects.filter(rol='ROL2', activo=1).values('email')
        ))
        if not destinatarios:
            raise CommandError('No hay usuarios ROL2 activos para turnar las solicitudes.')

        medios_registro = list(MedioRecepcion.objects.filter(activo=1))
        medios_turnado = list(MedioRecepcion.objects.filter(activo=1, paraTurnado=1))
        criterios_por_nivel = {
            nivel: list(PrioridadCriterio.objects.filter(activo=1, nivel=nivel).values_list('descripcionCriterio', flat=True))
            for nivel in ('Alta', 'Media', 'Baja')
        }

        ahora = timezone.now()
        creados = 0

        for i in range(cantidad):
            caso_desc, caso_ctx = CASOS[i % len(CASOS)]

            # Antigüedad repartida en los últimos ~5 meses, con más solicitudes
            # recientes que antiguas (más realista que una distribución pareja).
            dias_atras = int(random.triangular(0, 150, 8))
            fecha_registro = ahora - timezone.timedelta(
                days=dias_atras, hours=random.randint(0, 9), minutes=random.randint(0, 59),
            )

            prioridad = random.choices(['Alta', 'Media', 'Baja'], weights=[0.22, 0.45, 0.33])[0]
            opciones_criterio = criterios_por_nivel.get(prioridad) or []
            criterios = ' | '.join(random.sample(opciones_criterio, k=min(2, len(opciones_criterio)))) if opciones_criterio else ''

            dias_sla = {'Alta': (3, 5), 'Media': (7, 12), 'Baja': (14, 21)}[prioridad]
            fecha_limite = fecha_registro + timezone.timedelta(days=random.randint(*dias_sla))

            # Entre más vieja la solicitud, más probable que ya esté resuelta —
            # así los estatus reflejan el paso del tiempo en vez de ser al azar.
            if dias_atras > 60:
                estado = random.choices(
                    ['Concluido', 'Rechazado', 'Pendiente_validacion'], weights=[0.78, 0.12, 0.10],
                )[0]
            elif dias_atras > 25:
                estado = random.choices(
                    ['Concluido', 'Atendido', 'Turnado', 'Pendiente_validacion', 'Rechazado'],
                    weights=[0.45, 0.28, 0.12, 0.10, 0.05],
                )[0]
            elif dias_atras > 7:
                estado = random.choices(
                    ['Atendido', 'Turnado', 'Concluido', 'Registrado'], weights=[0.40, 0.30, 0.20, 0.10],
                )[0]
            else:
                estado = random.choices(
                    ['Registrado', 'Turnado', 'Atendido'], weights=[0.45, 0.35, 0.20],
                )[0]

            # Fuerza algunos vencidos y algunos por vencer entre los que siguen
            # abiertos, para que la temporalidad se vea variada en Consultar FUS.
            if estado in ('Registrado', 'Turnado', 'Atendido'):
                variante = random.random()
                if variante < 0.22:
                    fecha_limite = ahora - timezone.timedelta(days=random.randint(1, 6))  # vencido
                elif variante < 0.40:
                    fecha_limite = ahora + timezone.timedelta(days=random.randint(0, 2))  # por vencer

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
                estatusParticular_id=estado,
                fechaLimite=fecha_limite,
                idUsuarioRegistra=remitente.id,
            )
            # fechaRegistro es auto_now_add — se corrige después con un UPDATE
            # (que sí respeta el valor explícito) para que quede repartida en
            # el tiempo en vez de "ahora" para las 30+ solicitudes.
            FUS.objects.filter(pk=fus.pk).update(
                fechaRegistro=fecha_registro, fechaModificacion=fecha_registro,
            )

            if estado != 'Registrado':
                destinatario = random.choice(destinatarios)
                fecha_turnado = fecha_registro + timezone.timedelta(
                    hours=random.randint(1, 30),
                )
                estatus_titular = {
                    'Turnado': 'Recibido',
                    'Atendido': 'En_seguimiento',
                    'Pendiente_validacion': 'Concluido',
                    'Concluido': 'Concluido',
                    'Rechazado': 'Concluido',
                }[estado]
                turnado = Turnado.objects.create(
                    idFus=fus,
                    idRemitente=remitente,
                    idDestinatario=destinatario,
                    idMedio=random.choice(medios_turnado),
                    solicitudTexto='Se turna para su atención, seguimiento y respuesta correspondiente.',
                    fechaHoraTurnado=fecha_turnado,
                    estatusTitular_id=estatus_titular,
                    idUsuarioRegistra=remitente.id,
                )
                Turnado.objects.filter(pk=turnado.pk).update(fechaRegistro=fecha_turnado)

                if estado in ('Atendido', 'Pendiente_validacion', 'Concluido', 'Rechazado'):
                    n_respuestas = random.randint(1, 3)
                    fecha_resp = fecha_turnado
                    for r in range(n_respuestas):
                        fecha_resp = fecha_resp + timezone.timedelta(
                            days=random.randint(1, 3), hours=random.randint(0, 8),
                        )
                        es_ultima = r == n_respuestas - 1
                        seguimiento = Seguimiento.objects.create(
                            idTurnado=turnado,
                            fechaActividad=fecha_resp.date(),
                            descripcionActividad=(
                                'Se concluye la atención del asunto conforme a lo solicitado; '
                                'se informa al área correspondiente el resultado del trámite.'
                                if es_ultima and estatus_titular == 'Concluido'
                                else 'Se da seguimiento al asunto: se solicitó información adicional '
                                     'al área operativa involucrada y se está a la espera de respuesta.'
                            ),
                            accionTexto='Notificar al solicitante el resultado final.' if es_ultima else None,
                            idUsuarioRegistra=destinatario.id,
                        )
                        Seguimiento.objects.filter(pk=seguimiento.pk).update(fechaRegistro=fecha_resp)

            if estado == 'Concluido':
                fecha_conclusion = fecha_turnado + timezone.timedelta(days=random.randint(2, 15))
                if fecha_conclusion > ahora:
                    fecha_conclusion = ahora - timezone.timedelta(hours=random.randint(1, 48))
                FUS.objects.filter(pk=fus.pk).update(fechaConclusion=fecha_conclusion)

            creados += 1

        self.stdout.write(self.style.SUCCESS(f'Se crearon {creados} FUS de prueba (folios {ahora.year}).'))
