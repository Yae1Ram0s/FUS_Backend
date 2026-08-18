import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EventoUso',
            fields=[
                ('idEvento', models.UUIDField(db_column='id_evento', default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('fechaServidor', models.DateTimeField(auto_now_add=True, db_column='fecha_servidor')),
                ('ocurridoEn', models.DateTimeField(blank=True, db_column='ocurrido_en', null=True)),
                ('rolSnapshot', models.CharField(blank=True, db_column='rol_snapshot', default='', max_length=30)),
                ('unidadSnapshot', models.CharField(blank=True, db_column='unidad_snapshot', default='', max_length=255)),
                ('sesionId', models.CharField(blank=True, db_column='sesion_id', default='', max_length=64)),
                ('modulo', models.CharField(max_length=40)),
                ('componente', models.CharField(max_length=80)),
                ('evento', models.CharField(max_length=40)),
                ('accion', models.CharField(blank=True, default='', max_length=80)),
                ('resultado', models.CharField(choices=[('RECORDED', 'Registrado'), ('STARTED', 'Iniciado'), ('SUBMITTED', 'Enviado'), ('COMPLETED', 'Completado'), ('FAILED', 'Fallido'), ('ABANDONED', 'Abandonado')], default='RECORDED', max_length=12)),
                ('ruta', models.CharField(blank=True, default='', max_length=180)),
                ('duracionMs', models.PositiveIntegerField(blank=True, db_column='duracion_ms', null=True)),
                ('dispositivo', models.CharField(choices=[('ESCRITORIO', 'Escritorio'), ('MOVIL', 'Móvil'), ('TABLETA', 'Tableta'), ('DESCONOCIDO', 'Desconocido')], default='DESCONOCIDO', max_length=16)),
                ('viewportWidth', models.PositiveSmallIntegerField(blank=True, db_column='viewport_width', null=True)),
                ('appVersion', models.CharField(blank=True, db_column='app_version', default='', max_length=40)),
                ('metadatos', models.JSONField(blank=True, default=dict)),
                ('usuario', models.ForeignKey(blank=True, db_column='usuario_id', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='eventos_uso', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'scs_analitica_eventos_uso',
                'ordering': ['-fechaServidor'],
                'indexes': [
                    models.Index(fields=['-fechaServidor'], name='idx_an_evento_fecha'),
                    models.Index(fields=['modulo', '-fechaServidor'], name='idx_an_modulo_fecha'),
                    models.Index(fields=['usuario', '-fechaServidor'], name='idx_an_usuario_fecha'),
                    models.Index(fields=['rolSnapshot', '-fechaServidor'], name='idx_an_rol_fecha'),
                    models.Index(fields=['dispositivo', '-fechaServidor'], name='idx_an_disp_fecha'),
                    models.Index(fields=['sesionId', '-fechaServidor'], name='idx_an_sesion_fecha'),
                    models.Index(fields=['resultado', '-fechaServidor'], name='idx_an_result_fecha'),
                ],
            },
        ),
    ]
