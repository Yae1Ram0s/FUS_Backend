from django.db import migrations


def seed_estatus(apps, schema_editor):
    Estatus = apps.get_model('catalogos', 'Estatus')
    Estatus.objects.get_or_create(
        clave='Rechazado',
        defaults={'nombre': 'Rechazado', 'tipoFlujo': 'PARTICULAR', 'orden': 6},
    )


def remove_estatus(apps, schema_editor):
    Estatus = apps.get_model('catalogos', 'Estatus')
    Estatus.objects.filter(clave='Rechazado').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalogos', '0007_estatus_pendiente_validacion'),
    ]

    operations = [
        migrations.RunPython(seed_estatus, reverse_code=remove_estatus),
    ]
