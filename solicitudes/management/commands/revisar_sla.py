"""Notifica a ROL1/ROL2 los FUS turnados cuyo SLA (fechaLimite) está por
vencer (dentro de las próximas 24h).

Este comando NO se agenda solo — debe correr periódicamente vía un
scheduler externo (Railway Cron Jobs, cron del servidor, etc.). Ejecutar
manualmente con:

    python manage.py revisar_sla
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from solicitudes.models import FUS, Turnado, Notificacion
from solicitudes.views.turnado import _push_notificacion
from solicitudes.helpers import notificar_por_correo


class Command(BaseCommand):
    help = 'Notifica a ROL1/ROL2 los FUS turnados cuyo SLA está por vencer (<=24h).'

    def handle(self, *args, **options):
        ahora = timezone.now()

        candidatos = FUS.objects.filter(
            activo=1,
            estatusParticular_id='Turnado',
            fechaLimite__isnull=False,
            fechaLimite__gt=ahora,
            fechaLimite__lte=ahora + timedelta(hours=24),
        )

        creadas = 0
        for fus in candidatos:
            ya_notificado = Notificacion.objects.filter(
                fusFolio=fus.folio,
                tipoEvento='SLA_POR_VENCER',
                fechaGeneracion__gte=ahora - timedelta(hours=24),
            ).exists()
            if ya_notificado:
                continue

            turnado_activo = Turnado.objects.filter(
                idFus=fus, activo=1
            ).exclude(estatusTitular_id='Concluido').first()

            destinatarios = []
            if fus.idSolicitanteInterno_id:
                destinatarios.append(fus.idSolicitanteInterno)
            if turnado_activo and turnado_activo.idDestinatario_id:
                destinatarios.append(turnado_activo.idDestinatario)

            mensaje = f"El FUS {fus.folio} está por vencer (límite: {fus.fechaLimite})."

            for dest in destinatarios:
                notif = Notificacion.objects.create(
                    idDestinatario=dest,
                    fusFolio=fus.folio,
                    tipoEvento='SLA_POR_VENCER',
                    mensaje=mensaje,
                )
                _push_notificacion(notif)
                notificar_por_correo(notif)
                creadas += 1

        self.stdout.write(self.style.SUCCESS(f'{creadas} notificaciones de SLA creadas.'))
