from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('solicitudes', '0027_evidencia_tamano_bytes')]

    operations = [
        migrations.AddIndex(model_name='fus', index=models.Index(fields=['fechaLimite'], name='idx_fus_limite')),
        migrations.AddIndex(model_name='fus', index=models.Index(fields=['fechaConclusion'], name='idx_fus_conclusion')),
        migrations.AddIndex(model_name='fus', index=models.Index(fields=['prioridad'], name='idx_fus_prioridad')),
        migrations.AddIndex(model_name='fus', index=models.Index(fields=['idComisionado'], name='idx_fus_comisionado')),
        migrations.AddIndex(model_name='fus', index=models.Index(fields=['activo', 'fechaRegistro'], name='idx_fus_act_fecha')),
        migrations.AddIndex(model_name='turnado', index=models.Index(fields=['fechaHoraTurnado'], name='idx_turnado_fecha')),
        migrations.AddIndex(model_name='seguimientorespuesta', index=models.Index(fields=['idFus', 'fechaRegistro'], name='idx_seg_fus_fecha')),
        migrations.AddIndex(model_name='notificacion', index=models.Index(fields=['idDestinatario', 'leida'], name='idx_notif_dest_leida')),
    ]
