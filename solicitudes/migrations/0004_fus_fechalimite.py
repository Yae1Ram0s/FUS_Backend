from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solicitudes', '0003_seguimiento_accion_texto'),
    ]

    operations = [
        migrations.AddField(
            model_name='fus',
            name='fechaLimite',
            field=models.DateField(blank=True, null=True),
        ),
    ]
