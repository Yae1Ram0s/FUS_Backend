from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from analitica.models import EventoUso


class Command(BaseCommand):
    help = 'Elimina eventos de analítica anteriores a la política de retención.'

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=180, help='Días de retención (mínimo 30).')
        parser.add_argument('--dry-run', action='store_true', help='Solo informa cuántos eventos se eliminarían.')

    def handle(self, *args, **options):
        dias = options['dias']
        if dias < 30:
            raise CommandError('La retención mínima permitida es de 30 días.')
        limite = timezone.now() - timedelta(days=dias)
        candidatos = EventoUso.objects.filter(fechaServidor__lt=limite)
        total = candidatos.count()
        if options['dry_run']:
            self.stdout.write(f'DRY-RUN: {total} evento(s) anteriores a {limite.isoformat()}.')
            return
        eliminados, _ = candidatos.delete()
        self.stdout.write(self.style.SUCCESS(f'Depuración terminada: {eliminados} evento(s) eliminados.'))
