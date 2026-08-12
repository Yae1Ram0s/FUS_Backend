from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('autenticacion', '0010_historialsalud')]

    operations = [
        migrations.AddField(
            model_name='codigootp', name='estadoEnvio',
            field=models.CharField(
                choices=[('SIN_CONFIRMACION', 'Sin confirmación'), ('ENVIADO', 'Enviado'), ('ERROR', 'Error')],
                db_column='estado_envio', default='SIN_CONFIRMACION', max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='codigootp', name='fechaEnvio',
            field=models.DateTimeField(blank=True, db_column='fecha_envio', null=True),
        ),
        migrations.AddField(
            model_name='codigootp', name='detalleEnvio',
            field=models.CharField(blank=True, db_column='detalle_envio', default='', max_length=160),
        ),
        migrations.AddIndex(
            model_name='codigootp',
            index=models.Index(fields=['-fechaGeneracion', 'estadoEnvio'], name='idx_otp_fecha_estado'),
        ),
    ]
