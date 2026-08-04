from django.db import migrations, models


RENOMBRES = [
    ('idUnidadAdministrativa', 'id'),
    ('unidadAdministrativa', 'nombre'),
    ('esUnidadAdministrativa', 'es_unidad_administrativa'),
    ('esUnidadDeNegocio', 'es_unidad_negocio'),
    ('fechaRegistro', 'fecha_registro'),
    ('fechaModificacion', 'fecha_modificacion'),
    ('idUsuarioRegistra', 'usuario_registra_id'),
    ('idUsuarioModifica', 'usuario_modifica_id'),
]


class Migration(migrations.Migration):

    dependencies = [('catalogos', '0012_renombrar_columnas_catalogos')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        f'ALTER TABLE scs_cat_unidades_administrativas '
                        f'RENAME COLUMN {anterior} TO {nuevo}'
                    ),
                    reverse_sql=(
                        f'ALTER TABLE scs_cat_unidades_administrativas '
                        f'RENAME COLUMN {nuevo} TO {anterior}'
                    ),
                )
                for anterior, nuevo in RENOMBRES
            ],
            state_operations=[
                migrations.AlterField(model_name='unidadadministrativa', name='idUnidadAdministrativa', field=models.AutoField(db_column='id', primary_key=True, serialize=False)),
                migrations.AlterField(model_name='unidadadministrativa', name='unidadAdministrativa', field=models.CharField(blank=True, db_column='nombre', max_length=255, null=True)),
                migrations.AlterField(model_name='unidadadministrativa', name='esUnidadAdministrativa', field=models.IntegerField(db_column='es_unidad_administrativa', default=0)),
                migrations.AlterField(model_name='unidadadministrativa', name='esUnidadDeNegocio', field=models.IntegerField(db_column='es_unidad_negocio', default=0)),
                migrations.AlterField(model_name='unidadadministrativa', name='fechaRegistro', field=models.CharField(blank=True, db_column='fecha_registro', max_length=50, null=True)),
                migrations.AlterField(model_name='unidadadministrativa', name='fechaModificacion', field=models.CharField(blank=True, db_column='fecha_modificacion', max_length=50, null=True)),
                migrations.AlterField(model_name='unidadadministrativa', name='idUsuarioRegistra', field=models.IntegerField(blank=True, db_column='usuario_registra_id', null=True)),
                migrations.AlterField(model_name='unidadadministrativa', name='idUsuarioModifica', field=models.IntegerField(blank=True, db_column='usuario_modifica_id', null=True)),
            ],
        ),
    ]
