from django.db import migrations


def seed_estatus(apps, schema_editor):
    Estatus = apps.get_model('catalogos', 'Estatus')
    Estatus.objects.get_or_create(
        clave='Pendiente_validacion',
        defaults={'nombre': 'Pendiente de validación', 'tipoFlujo': 'PARTICULAR', 'orden': 5},
    )


def remove_estatus(apps, schema_editor):
    Estatus = apps.get_model('catalogos', 'Estatus')
    Estatus.objects.filter(clave='Pendiente_validacion').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalogos', '0006_unidadadministrativa'),
    ]

    operations = [
        migrations.RunPython(seed_estatus, reverse_code=remove_estatus),
    ]
