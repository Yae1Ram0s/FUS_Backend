"""Guarda una foto del estado de `_health()` (ver admin_views.py) para poder
graficar disponibilidad/latencia en el tiempo en el panel de administrador —
sin esto, AdminSaludView solo refleja el instante en que se consulta y no
queda ningún historial.

Este comando NO se agenda solo — debe correr periódicamente vía un scheduler
externo (Railway Cron Jobs, cron del servidor, etc.), igual que revisar_sla.
Frecuencia sugerida: cada 15-30 min. Ejecutar manualmente con:

    python manage.py registrar_salud_sistema
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from autenticacion.admin_views import _health
from autenticacion.models import HistorialSalud

RETENCION_DIAS = 30


class Command(BaseCommand):
    help = 'Guarda una foto de _health() en HistorialSalud y purga las de hace más de 30 días.'

    def handle(self, *args, **options):
        try:
            resultado = _health()
        except Exception as exc:
            resultado = {'estado': 'degradado', 'error': exc.__class__.__name__}

        HistorialSalud.objects.create(estado=resultado.get('estado', 'degradado'), detalle=resultado)
        borradas, _ = HistorialSalud.objects.filter(
            fechaHora__lt=timezone.now() - timezone.timedelta(days=RETENCION_DIAS),
        ).delete()

        self.stdout.write(self.style.SUCCESS(f"Salud registrada: {resultado.get('estado')}. {borradas} snapshots antiguos purgados."))
