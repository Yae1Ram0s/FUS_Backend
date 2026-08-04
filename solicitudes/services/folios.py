from django.db import transaction

from ..models import FUS

ROL_SEGMENTO = {
    'ROL1': 'PARTICULAR',
    'ROL2': 'TITULAR',
    'EQUIPO_PARTICULAR': 'PARTICULAR',
}


def generar_folio(rol, year):
    """Genera el siguiente folio FUS dentro de una transacción."""
    with transaction.atomic():
        consecutivo = (
            FUS.objects.select_for_update()
            .filter(fechaRegistro__year=year)
            .count()
            + 1
        )
        segmento = ROL_SEGMENTO.get(rol, rol)
        return f'ANAM/{segmento}/FUS/{consecutivo:04d}/{year}'
