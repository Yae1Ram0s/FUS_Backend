"""Notifica a ROL1/ROL2 los FUS activos cuyo límite de respuesta (fechaLimite)
está por vencer — no solo turnados, cualquier FUS con fechaLimite (mismo
criterio de aplicabilidad que estadoTemporalidad en FUSSerializer).

Ventana de aviso, según qué tan lejos esté el límite:
  - Límite el mismo día calendario (hoy): se avisa cuando falten <= 2 horas.
  - Límite en un día futuro: se avisa cuando falte <= 1 día completo.

Este comando NO se agenda solo — debe correr periódicamente vía un
scheduler externo (Railway Cron Jobs, cron del servidor, etc.). Para que la
ventana de 2h en FUS con límite hoy no se salte entre corridas, debe correr
con una frecuencia menor a esas 2 horas (ideal: cada 15-30 min). Ejecutar
manualmente con:

    python manage.py revisar_sla
"""
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from solicitudes.models import FUS, Turnado, Notificacion
from solicitudes.services import notificar_por_correo, push_notificacion


class Command(BaseCommand):
    help = 'Notifica los FUS cuyo límite de respuesta está por vencer (hoy: <=2h, día futuro: <=1 día).'

    def handle(self, *args, **options):
        ahora = timezone.now()
        hoy = timezone.localtime(ahora).date()

        # Límites de "hoy" en hora local, convertidos a datetime aware — no se
        # usa el lookup `fechaLimite__date=hoy` porque en MySQL requiere
        # CONVERT_TZ, que devuelve NULL en silencio si el servidor no tiene
        # cargadas las tablas de zona horaria (vacía el filtro para todos los
        # FUS sin ningún error) — mismo problema ya documentado y evitado en
        # views/bitacora.py:_parse_fecha_local.
        inicio_hoy = timezone.make_aware(
            datetime.combine(hoy, time.min), timezone.get_current_timezone(),
        )
        fin_hoy = inicio_hoy + timedelta(days=1)

        base = FUS.objects.filter(
            activo=1,
            fechaLimite__isnull=False,
        ).exclude(estatusParticular_id='Concluido')

        # Límite hoy mismo (día calendario, hora local) — ventana corta de 2h.
        candidatos_hoy = base.filter(
            fechaLimite__gte=inicio_hoy,
            fechaLimite__lt=fin_hoy,
            fechaLimite__gt=ahora,
            fechaLimite__lte=ahora + timedelta(hours=2),
        )

        # Límite en un día futuro — ventana de 1 día completo.
        candidatos_futuro = base.filter(
            fechaLimite__gte=fin_hoy,
            fechaLimite__gt=ahora,
            fechaLimite__lte=ahora + timedelta(days=1),
        )

        # dict por id evita duplicados si un FUS calificara por ambas listas
        # (no debería pasar dado que son mutuamente excluyentes por fecha,
        # pero es una salvaguarda barata).
        candidatos = {f.id: f for f in list(candidatos_hoy) + list(candidatos_futuro)}.values()

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
                push_notificacion(notif)
                notificar_por_correo(notif)
                creadas += 1

        self.stdout.write(self.style.SUCCESS(f'{creadas} notificaciones de SLA creadas.'))
