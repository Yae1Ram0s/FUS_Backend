import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('solicitudes', '0028_indices_reportes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ReporteGuardado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=200)),
                ('formato', models.CharField(choices=[('pdf', 'PDF'), ('excel', 'Excel'), ('pptx', 'Presentación')], max_length=10)),
                ('filtros', models.JSONField(blank=True, default=dict)),
                ('secciones', models.JSONField(blank=True, default=list)),
                ('nombreArchivo', models.CharField(db_column='nombre_archivo', max_length=255)),
                ('rutaArchivo', models.CharField(db_column='ruta_archivo', max_length=500)),
                ('fechaCreacion', models.DateTimeField(auto_now_add=True, db_column='fecha_creacion')),
                ('idUsuario', models.ForeignKey(db_column='usuario_id', on_delete=django.db.models.deletion.CASCADE, related_name='reportes_guardados', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'scs_tbl_reportes_guardados',
                'ordering': ['-fechaCreacion'],
            },
        ),
    ]
