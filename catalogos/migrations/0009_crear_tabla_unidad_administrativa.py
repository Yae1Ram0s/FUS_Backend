# UnidadAdministrativa tiene managed=False (tabla externa/legacy, ver
# 0006_unidadadministrativa.py) — Django nunca emitió un CREATE TABLE real
# para ella, así que solo existe en la base de datos de desarrollo porque se
# creó manualmente fuera de las migraciones. Cualquier base nueva (incluida
# la de pruebas, que se crea desde cero en cada `manage.py test`) se queda
# sin la tabla y truena en el primer JOIN contra CorreoAutorizado.
# `IF NOT EXISTS` la deja como no-op en la base real, que ya la tiene.
from django.db import migrations

SQL_CREAR_TABLA = """
CREATE TABLE IF NOT EXISTS scg_cat_unidad_administrativa (
  idUnidadAdministrativa int DEFAULT NULL,
  clave text,
  unidadAdministrativa text,
  esUnidadAdministrativa int DEFAULT NULL,
  esUnidadDeNegocio int DEFAULT NULL,
  fechaRegistro text,
  fechaModificacion text,
  idUsuarioRegistra int DEFAULT NULL,
  idUsuarioModifica int DEFAULT NULL,
  activo int DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

SQL_BORRAR_TABLA = "DROP TABLE IF EXISTS scg_cat_unidad_administrativa;"


class Migration(migrations.Migration):

    dependencies = [
        ('catalogos', '0008_estatus_rechazado'),
    ]

    operations = [
        # state_operations vacío a propósito: el estado del modelo
        # (UnidadAdministrativa, managed=False) ya lo registró
        # 0006_unidadadministrativa — esto solo emite el DDL que faltaba.
        migrations.RunSQL(sql=SQL_CREAR_TABLA, reverse_sql=SQL_BORRAR_TABLA, state_operations=[]),
    ]
