# Auditoría de producción — FUSListCreateView.get (views/fus.py, no tocado
# aquí) arma un filtro `search` con Q(...) | Q(...) sobre `icontains` en
# varias columnas de texto libre de FUS/Evidencia/Turnado/Seguimiento.
# Ninguna de esas columnas tenía índice, y aunque lo tuviera, un B-tree
# normal (db_index=True) no sirve de nada contra `LIKE '%término%'`
# (comodín al inicio) — eso aplica igual en InnoDB que en Postgres.
#
# La única aceleración real para "contiene esta palabra en cualquier
# parte" en MySQL/InnoDB es un índice FULLTEXT nativo (soportado en InnoDB
# desde 5.6+; confirmado en este entorno con VERSION() = 9.7.0, tablas ya
# en InnoDB), usable después vía MATCH(...) AGAINST(...). Django no expone
# una clase de índice FULLTEXT de primera clase para MySQL en el ORM, así
# que se crea con RunSQL directo.
#
# Alcance original: esta migración solo agregaba los índices, sin tocar
# views/fus.py. views/fus.py ya usa estos índices vía MATCH()...AGAINST()
# IN BOOLEAN MODE (ver FUSListCreateView.get / _termino_fulltext_booleano) —
# con respaldo a icontains cuando el término de búsqueda es más corto que
# innodb_ft_min_token_size, para no perder resultados en ese caso.
#
# Columnas elegidas — las de texto libre más buscadas y con mayor volumen
# de contenido, mapeadas 1:1 al patrón OR-entre-columnas que ya usa la
# vista (un índice FULLTEXT multi-columna permite MATCH(col1, col2) AGAINST
# más adelante, cubriendo en una sola búsqueda lo que hoy son dos Q()):
#   - scs_tbl_fus(descripcion, contexto)
#   - scs_tbl_evidencias(nombre_archivo, comentarios)
#   - scs_tbl_turnados(solicitud_texto)
# Deliberadamente fuera de esta migración: FUS.medioEspecificacion/
# criterios/nombreExterno/telefonoExterno/correoExterno y las columnas de
# Seguimiento (descripcionActividad/accionTexto). Los primeros son campos
# más cortos/estructurados donde lo que de verdad se busca es una
# subcadena (parte de un teléfono, un dominio de correo) — algo que un
# FULLTEXT nunca acelera porque indexa palabras completas, no subcadenas.
# Seguimiento queda fuera para mantener el bloque acotado a lo mínimo
# pedido por la auditoría; es candidato razonable para un bloque futuro
# si se decide extender la cobertura.
from django.db import migrations

# Una sentencia por RunSQL a propósito: mysqlclient no ejecuta varias
# sentencias separadas por ";" en una sola llamada a cursor.execute() salvo
# que la conexión active CLIENT.MULTI_STATEMENTS, y Django no lo hace por
# defecto — juntarlas en un solo string habría fallado en tiempo real.

SQL_CREAR_IDX_FUS = (
    "CREATE FULLTEXT INDEX idx_fus_fulltext_busqueda "
    "ON scs_tbl_fus (descripcion, contexto);"
)
SQL_BORRAR_IDX_FUS = "DROP INDEX idx_fus_fulltext_busqueda ON scs_tbl_fus;"

SQL_CREAR_IDX_EVIDENCIA = (
    "CREATE FULLTEXT INDEX idx_evidencia_fulltext_busqueda "
    "ON scs_tbl_evidencias (nombre_archivo, comentarios);"
)
SQL_BORRAR_IDX_EVIDENCIA = (
    "DROP INDEX idx_evidencia_fulltext_busqueda ON scs_tbl_evidencias;"
)

SQL_CREAR_IDX_TURNADO = (
    "CREATE FULLTEXT INDEX idx_turnado_fulltext_busqueda "
    "ON scs_tbl_turnados (solicitud_texto);"
)
SQL_BORRAR_IDX_TURNADO = (
    "DROP INDEX idx_turnado_fulltext_busqueda ON scs_tbl_turnados;"
)


# CREATE FULLTEXT INDEX es sintaxis exclusiva de MySQL/InnoDB — en cualquier
# otro motor (Postgres/Neon en Render, ver backend/settings.py DATABASE_URL)
# la sentencia ni siquiera es válida y tronaba `migrate` con exit status 1
# en el build de Render. Los índices son solo una optimización (ver
# FUSListCreateView.get / _termino_fulltext_booleano, que ya cae a icontains
# cuando no aplica), así que en otros motores esta migración simplemente no
# hace nada — no hay un equivalente 1:1 de FULLTEXT que valga la pena emular
# aquí para un motor que de momento no la usa.
def crear_indices_fulltext(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    schema_editor.execute(SQL_CREAR_IDX_FUS)
    schema_editor.execute(SQL_CREAR_IDX_EVIDENCIA)
    schema_editor.execute(SQL_CREAR_IDX_TURNADO)


def borrar_indices_fulltext(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    schema_editor.execute(SQL_BORRAR_IDX_TURNADO)
    schema_editor.execute(SQL_BORRAR_IDX_EVIDENCIA)
    schema_editor.execute(SQL_BORRAR_IDX_FUS)


class Migration(migrations.Migration):
    # MySQL no soporta DDL transaccional (no puede hacer rollback de un
    # CREATE INDEX) — con la migración envuelta en una transacción implícita
    # (default), Django rechaza ejecutar el DDL de arriba con
    # TransactionManagementError. RunSQL lo manejaba solo; RunPython
    # necesita este atomic=False explícito para el mismo caso.
    atomic = False

    dependencies = [
        ('solicitudes', '0032_turnado_medioespecificacion'),
    ]

    operations = [
        # state_operations no aplica: no hay una representación de FULLTEXT
        # en el ORM de Django para MySQL, así que esto no modifica el
        # estado de ningún campo/modelo — solo emite el DDL del índice.
        migrations.RunPython(crear_indices_fulltext, borrar_indices_fulltext),
    ]
