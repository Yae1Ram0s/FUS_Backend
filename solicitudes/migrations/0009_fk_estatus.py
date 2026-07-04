from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalogos', '0005_estatus'),
        ('solicitudes', '0008_merge_solicitante_externo_into_fus'),
    ]

    operations = [
        # Eliminar índice manual antes de que FK cree el suyo en la misma columna
        migrations.RemoveIndex(
            model_name='fus',
            name='idx_fus_estatus',
        ),
        migrations.AlterField(
            model_name='fus',
            name='estatusParticular',
            field=models.ForeignKey(
                db_column='estatusParticular',
                default='Registrado',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='fus_set',
                to='catalogos.estatus',
                to_field='clave',
            ),
        ),
        migrations.RemoveIndex(
            model_name='turnado',
            name='idx_turnado_estatus',
        ),
        migrations.AlterField(
            model_name='turnado',
            name='estatusTitular',
            field=models.ForeignKey(
                db_column='estatusTitular',
                default='Recibido',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='turnados_set',
                to='catalogos.estatus',
                to_field='clave',
            ),
        ),
    ]
