from django.core.management.base import BaseCommand
from django.db import transaction

from solicitudes.estatus_efectivo import debe_quedar_rechazado
from solicitudes.models import FUS


class Command(BaseCommand):
    help = (
        "Corrige FUS cuyo estatus a nivel FUS contradice el de sus turnados: "
        "todas las personas turnadas activas están 'Rechazado' pero el FUS "
        "sigue en 'Atendido'/'Pendiente_validacion' (rechazos hechos antes de "
        "que RechazarPersonaTurnadoView actualizara el FUS). Sin --aplicar "
        "solo lista lo que cambiaría."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--aplicar', action='store_true',
            help='Guarda los cambios (por defecto solo se muestran).',
        )

    def handle(self, *args, **options):
        aplicar = options['aplicar']
        candidatos = []
        for fus in FUS.objects.filter(activo=1).prefetch_related('turnados'):
            estatus_turnados = [t.estatusTitular_id for t in fus.turnados.all() if t.activo]
            if debe_quedar_rechazado(fus.estatusParticular_id, estatus_turnados):
                candidatos.append(fus)

        if not candidatos:
            self.stdout.write('Nada que corregir: ningún FUS contradice a sus turnados.')
            return

        with transaction.atomic():
            for fus in candidatos:
                self.stdout.write(f'{fus.folio}: {fus.estatusParticular_id} -> Rechazado')
                if aplicar:
                    fus.estatusParticular_id = 'Rechazado'
                    fus.save()

        if aplicar:
            self.stdout.write(self.style.SUCCESS(f'{len(candidatos)} FUS corregido(s).'))
        else:
            self.stdout.write(
                f'{len(candidatos)} FUS por corregir. Corre de nuevo con --aplicar para guardar.'
            )
