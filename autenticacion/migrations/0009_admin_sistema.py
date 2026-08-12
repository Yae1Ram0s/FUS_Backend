from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('autenticacion', '0008_renombrar_columnas_autenticacion'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AlterField(model_name='correoautorizado', name='rol', field=models.CharField(choices=[('ROL1', 'Particular del Titular'), ('ROL2', 'Titular / Enlace Estratégico'), ('COMISIONADO', 'Comisionado'), ('EQUIPO_PARTICULAR', 'Equipo del Particular'), ('ADMIN', 'Administrador del sistema')], max_length=20)),
        migrations.CreateModel(name='SeguridadUsuario', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('requiereCambioContrasena', models.BooleanField(db_column='requiere_cambio_contrasena', default=False)),
            ('intentosFallidos', models.PositiveIntegerField(db_column='intentos_fallidos', default=0)),
            ('bloqueadoHasta', models.DateTimeField(blank=True, db_column='bloqueado_hasta', null=True)),
            ('versionSesion', models.PositiveIntegerField(db_column='version_sesion', default=0)),
            ('ultimoIngreso', models.DateTimeField(blank=True, db_column='ultimo_ingreso', null=True)),
            ('fechaModificacion', models.DateTimeField(auto_now=True, db_column='fecha_modificacion')),
            ('usuario', models.OneToOneField(db_column='usuario_id', on_delete=django.db.models.deletion.CASCADE, related_name='seguridad_scs', to=settings.AUTH_USER_MODEL)),
        ], options={'db_table': 'scs_auth_seguridad_usuario'}),
        migrations.CreateModel(name='AuditoriaAdministrativa', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('actorEmail', models.EmailField(db_column='actor_email', max_length=254)),
            ('objetivoEmail', models.EmailField(blank=True, db_column='objetivo_email', default='', max_length=254)),
            ('accion', models.CharField(max_length=60)), ('detalle', models.JSONField(blank=True, default=dict)),
            ('ipCliente', models.GenericIPAddressField(blank=True, db_column='ip_cliente', null=True)),
            ('fechaHora', models.DateTimeField(auto_now_add=True, db_column='fecha_hora')),
            ('actor', models.ForeignKey(db_column='actor_id', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ('objetivo', models.ForeignKey(blank=True, db_column='objetivo_id', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
        ], options={'db_table': 'scs_auth_auditoria_administrativa', 'ordering': ['-fechaHora']}),
        migrations.AddIndex(model_name='auditoriaadministrativa', index=models.Index(fields=['fechaHora'], name='idx_admin_aud_fecha')),
        migrations.AddIndex(model_name='auditoriaadministrativa', index=models.Index(fields=['actorEmail'], name='idx_admin_aud_actor')),
        migrations.AddIndex(model_name='auditoriaadministrativa', index=models.Index(fields=['objetivoEmail'], name='idx_admin_aud_objetivo')),
    ]
