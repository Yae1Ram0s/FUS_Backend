from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('catalogos', '0010_renombrar_tablas_catalogos'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE scg_cat_unidad_administrativa '
                        'RENAME TO scs_cat_unidades_administrativas'
                    ),
                    reverse_sql=(
                        'ALTER TABLE scs_cat_unidades_administrativas '
                        'RENAME TO scg_cat_unidad_administrativa'
                    ),
                ),
            ],
            state_operations=[
                migrations.AlterModelTable(
                    name='unidadadministrativa',
                    table='scs_cat_unidades_administrativas',
                ),
            ],
        ),
    ]
