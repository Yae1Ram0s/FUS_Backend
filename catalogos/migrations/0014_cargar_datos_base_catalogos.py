from django.db import migrations


CRITERIOS_PRIORIDAD = [
    (1, 'Alta', 'Posible corrupción, denuncia, falta administrativa o delito'),
    (2, 'Alta', 'Solicitud directa a la persona Titular sobre asunto sensible'),
    (3, 'Alta', 'Riesgo jurídico, administrativo, político, mediático, operativo o de seguridad'),
    (4, 'Alta', 'Plazo urgente'),
    (5, 'Alta', 'Posible afectación a derechos, recursos públicos o imagen institucional'),
    (6, 'Media', 'Sea relevante para la gestión institucional'),
    (7, 'Media', 'Requiera análisis o canalización'),
    (8, 'Media', 'No tenga riesgo inmediato'),
    (9, 'Media', 'No exija decisión urgente de la persona Titular'),
    (10, 'Media', 'Pueda resolverse por un área competente con seguimiento de la Oficina Particular'),
    (11, 'Media', 'Acceso a instalaciones, información o decisiones estratégicas'),
    (12, 'Baja', 'Sea informativa, protocolaria o de cortesía'),
    (13, 'Baja', 'No implique riesgo institucional'),
    (14, 'Baja', 'No tenga plazo crítico'),
    (15, 'Baja', 'No requiera intervención de la persona Titular'),
    (16, 'Baja', 'Pueda responderse con formato estándar, canalizarse o archivarse'),
]

MEDIOS_RECEPCION = [
    (1, 'WhatsApp', 1),
    (2, 'Llamada', 1),
    (3, 'Correo electrónico', 1),
    (4, 'Otro', 1),
    (5, 'Reunión', 0),
    (6, 'Recorrido', 0),
    (7, 'Solicitud en sitio', 0),
    (8, 'Redes sociales', 0),
    (9, 'Portal de transparencia', 0),
]


def cargar_catalogos(apps, schema_editor):
    PrioridadCriterio = apps.get_model('catalogos', 'PrioridadCriterio')
    MedioRecepcion = apps.get_model('catalogos', 'MedioRecepcion')
    UnidadAdministrativa = apps.get_model('catalogos', 'UnidadAdministrativa')

    for identificador, nivel, descripcion in CRITERIOS_PRIORIDAD:
        PrioridadCriterio.objects.update_or_create(
            id=identificador,
            defaults={
                'nivel': nivel,
                'descripcionCriterio': descripcion,
                'activo': 1,
            },
        )

    for identificador, nombre, para_turnado in MEDIOS_RECEPCION:
        MedioRecepcion.objects.update_or_create(
            id=identificador,
            defaults={
                'nombreMedio': nombre,
                'paraTurnado': para_turnado,
                'activo': 1,
            },
        )

    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE LOWER(table_schema) = 'scs'
              AND table_name = 'scg_cat_unidad_administrativa'
            """
        )
        if not cursor.fetchone()[0]:
            return
        cursor.execute(
            """
            SELECT idUnidadAdministrativa, clave, unidadAdministrativa,
                   esUnidadAdministrativa, esUnidadDeNegocio, fechaRegistro,
                   fechaModificacion, idUsuarioRegistra, idUsuarioModifica, activo
            FROM scs.scg_cat_unidad_administrativa
            """
        )
        unidades = cursor.fetchall()

    for unidad in unidades:
        UnidadAdministrativa.objects.update_or_create(
            idUnidadAdministrativa=unidad[0],
            defaults={
                'clave': unidad[1],
                'unidadAdministrativa': unidad[2],
                'esUnidadAdministrativa': unidad[3] or 0,
                'esUnidadDeNegocio': unidad[4] or 0,
                'fechaRegistro': unidad[5],
                'fechaModificacion': unidad[6],
                'idUsuarioRegistra': unidad[7],
                'idUsuarioModifica': unidad[8],
                'activo': unidad[9] if unidad[9] is not None else 1,
            },
        )


def retirar_catalogos(apps, schema_editor):
    apps.get_model('catalogos', 'PrioridadCriterio').objects.filter(
        id__in=[item[0] for item in CRITERIOS_PRIORIDAD]
    ).delete()
    apps.get_model('catalogos', 'MedioRecepcion').objects.filter(
        id__in=[item[0] for item in MEDIOS_RECEPCION]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [('catalogos', '0013_renombrar_columnas_unidades')]

    operations = [
        migrations.RunPython(cargar_catalogos, retirar_catalogos),
    ]
