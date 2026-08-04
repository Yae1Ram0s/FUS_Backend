from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('autenticacion', '0007_renombrar_tablas_autenticacion'),
        ('catalogos', '0011_renombrar_unidades_administrativas'),
    ]

    operations = [
        migrations.AlterField(
            model_name='correoautorizado',
            name='unidadAdministrativa',
            field=models.ForeignKey(
                blank=True,
                db_column='unidad_administrativa_id',
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='correos_autorizados',
                to='catalogos.unidadadministrativa',
            ),
        ),
        migrations.AlterField(
            model_name='correoautorizado',
            name='fechaRegistro',
            field=models.DateTimeField(auto_now_add=True, db_column='fecha_registro', null=True),
        ),
        migrations.AlterField(
            model_name='correoautorizado',
            name='fechaModificacion',
            field=models.DateTimeField(auto_now=True, db_column='fecha_modificacion', null=True),
        ),
        migrations.AlterField(
            model_name='correoautorizado',
            name='idUsuarioRegistra',
            field=models.IntegerField(blank=True, db_column='usuario_registra_id', null=True),
        ),
        migrations.AlterField(
            model_name='correoautorizado',
            name='idUsuarioModifica',
            field=models.IntegerField(blank=True, db_column='usuario_modifica_id', null=True),
        ),
        migrations.AlterField(
            model_name='codigootp',
            name='fechaGeneracion',
            field=models.DateTimeField(auto_now_add=True, db_column='fecha_generacion'),
        ),
        migrations.AlterField(
            model_name='codigootp',
            name='fechaExpiracion',
            field=models.DateTimeField(db_column='fecha_expiracion'),
        ),
        migrations.AlterField(
            model_name='codigootp',
            name='ipSolicitante',
            field=models.GenericIPAddressField(blank=True, db_column='ip_solicitante', null=True),
        ),
        migrations.AlterField(
            model_name='codigootp',
            name='intentosFallidos',
            field=models.PositiveSmallIntegerField(db_column='intentos_fallidos', default=0),
        ),
    ]
