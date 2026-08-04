from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('catalogos', '0011_renombrar_unidades_administrativas')]

    operations = [
        migrations.AlterField(model_name='estatus', name='fechaModificacion', field=models.DateTimeField(auto_now=True, db_column='fecha_modificacion', null=True)),
        migrations.AlterField(model_name='estatus', name='fechaRegistro', field=models.DateTimeField(auto_now_add=True, db_column='fecha_registro', null=True)),
        migrations.AlterField(model_name='estatus', name='idUsuarioModifica', field=models.IntegerField(blank=True, db_column='usuario_modifica_id', null=True)),
        migrations.AlterField(model_name='estatus', name='idUsuarioRegistra', field=models.IntegerField(blank=True, db_column='usuario_registra_id', null=True)),
        migrations.AlterField(model_name='estatus', name='tipoFlujo', field=models.CharField(choices=[('PARTICULAR', 'Particular (ROL1 – FUS)'), ('TITULAR', 'Titular (ROL2 – Turnado)'), ('AMBOS', 'Ambos flujos')], db_column='tipo_flujo', max_length=12)),
        migrations.AlterField(model_name='mediorecepcion', name='fechaModificacion', field=models.DateTimeField(auto_now=True, db_column='fecha_modificacion', null=True)),
        migrations.AlterField(model_name='mediorecepcion', name='fechaRegistro', field=models.DateTimeField(auto_now_add=True, db_column='fecha_registro', null=True)),
        migrations.AlterField(model_name='mediorecepcion', name='idUsuarioModifica', field=models.IntegerField(blank=True, db_column='usuario_modifica_id', null=True)),
        migrations.AlterField(model_name='mediorecepcion', name='idUsuarioRegistra', field=models.IntegerField(blank=True, db_column='usuario_registra_id', null=True)),
        migrations.AlterField(model_name='mediorecepcion', name='nombreMedio', field=models.CharField(blank=True, db_column='nombre_medio', max_length=255, null=True)),
        migrations.AlterField(model_name='mediorecepcion', name='paraTurnado', field=models.IntegerField(db_column='para_turnado', default=0)),
        migrations.AlterField(model_name='prioridadcriterio', name='descripcionCriterio', field=models.TextField(db_column='descripcion_criterio')),
        migrations.AlterField(model_name='prioridadcriterio', name='fechaModificacion', field=models.DateTimeField(auto_now=True, db_column='fecha_modificacion', null=True)),
        migrations.AlterField(model_name='prioridadcriterio', name='fechaRegistro', field=models.DateTimeField(auto_now_add=True, db_column='fecha_registro', null=True)),
        migrations.AlterField(model_name='prioridadcriterio', name='idUsuarioModifica', field=models.IntegerField(blank=True, db_column='usuario_modifica_id', null=True)),
        migrations.AlterField(model_name='prioridadcriterio', name='idUsuarioRegistra', field=models.IntegerField(blank=True, db_column='usuario_registra_id', null=True)),
    ]
