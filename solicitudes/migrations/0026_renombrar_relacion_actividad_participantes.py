from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('solicitudes', '0025_renombrar_columnas_seguimiento_comisionado'),
    ]

    operations = [
        migrations.AlterField(
            model_name='actividad',
            name='participantes',
            field=models.ManyToManyField(
                blank=True,
                db_table='scs_rel_actividad_participantes',
                related_name='actividades_invitado',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
