from django.db import migrations, models


def seed_estatus(apps, schema_editor):
    Estatus = apps.get_model('catalogos', 'Estatus')
    registros = [
        # --- ROL1 / FUS (estatusParticular) ---
        {'clave': 'Registrado',    'nombre': 'Registrado',    'tipoFlujo': 'PARTICULAR', 'orden': 1},
        {'clave': 'Turnado',       'nombre': 'Turnado',       'tipoFlujo': 'PARTICULAR', 'orden': 2},
        {'clave': 'Atendido',      'nombre': 'Atendido',      'tipoFlujo': 'PARTICULAR', 'orden': 3},
        # --- ROL2 / Turnado (estatusTitular) ---
        {'clave': 'Recibido',      'nombre': 'Recibido',      'tipoFlujo': 'TITULAR',    'orden': 1},
        {'clave': 'En_seguimiento','nombre': 'En seguimiento','tipoFlujo': 'TITULAR',    'orden': 2},
        # --- Compartido por ambos flujos ---
        {'clave': 'Concluido',     'nombre': 'Concluido',     'tipoFlujo': 'AMBOS',      'orden': 4},
    ]
    for r in registros:
        Estatus.objects.get_or_create(clave=r['clave'], defaults=r)


def remove_estatus(apps, schema_editor):
    Estatus = apps.get_model('catalogos', 'Estatus')
    Estatus.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalogos', '0004_rename_prioridad_criterios'),
    ]

    operations = [
        migrations.CreateModel(
            name='Estatus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('clave', models.CharField(max_length=20, unique=True)),
                ('nombre', models.CharField(max_length=60)),
                ('tipoFlujo', models.CharField(
                    choices=[
                        ('PARTICULAR', 'Particular (ROL1 – FUS)'),
                        ('TITULAR',    'Titular (ROL2 – Turnado)'),
                        ('AMBOS',      'Ambos flujos'),
                    ],
                    max_length=12,
                )),
                ('orden', models.PositiveSmallIntegerField(default=0)),
                ('fechaRegistro',     models.DateTimeField(auto_now_add=True, null=True)),
                ('idUsuarioRegistra', models.IntegerField(blank=True, null=True)),
                ('fechaModificacion', models.DateTimeField(auto_now=True, null=True)),
                ('idUsuarioModifica', models.IntegerField(blank=True, null=True)),
                ('activa', models.BooleanField(default=True)),
            ],
            options={
                'db_table': 'scs_tbl_estatus',
                'ordering': ['orden'],
            },
        ),
        migrations.RunPython(seed_estatus, reverse_code=remove_estatus),
    ]
