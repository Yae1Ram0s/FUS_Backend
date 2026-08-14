#!/usr/bin/env bash
set -euo pipefail

# Respaldo de la base de datos MySQL del servidor institucional — Neon lo
# hacía automáticamente; en un servidor propio no hay ningún respaldo si no
# se agenda esto de forma explícita (ver el hallazgo "Backups de la base de
# datos" de la auditoría de producción). Vuelca con mysqldump, comprime, y
# purga los respaldos con más de RETENCION_DIAS.
#
# Este script NO se agenda solo — mismo criterio que revisar_sla/
# registrar_salud_sistema (comandos de Django que tampoco se agendan solos).
# Agendar con cron:
#   crontab -e
#   0 3 * * * /ruta/al/proyecto/backend/scripts/respaldar_bd.sh >> /ruta/al/proyecto/backend/scripts/respaldar_bd.log 2>&1
#
# Restaurar un respaldo puntual:
#   gunzip -c backups/scs_AAAAMMDD_HHMMSS.sql.gz | mysql -u "$DB_USER" -p -h "$DB_HOST" -P "$DB_PORT" "$DB_NAME"

DIR_PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR_RESPALDOS="$DIR_PROYECTO/backups"
RETENCION_DIAS="${RETENCION_DIAS:-30}"

# Lee UNA variable de backend/.env como texto plano — nunca la evalúa como
# shell (a diferencia de `source .env`, que ejecutaría cualquier `$(...)` o
# backtick que la contraseña llegara a traer).
leer_env() {
  [ -f "$DIR_PROYECTO/.env" ] && grep -E "^$1=" "$DIR_PROYECTO/.env" | tail -n1 | cut -d'=' -f2-
}

DB_NAME="${DB_NAME:-$(leer_env DB_NAME)}"
DB_USER="${DB_USER:-$(leer_env DB_USER)}"
DB_PASSWORD="${DB_PASSWORD:-$(leer_env DB_PASSWORD)}"
DB_HOST="${DB_HOST:-$(leer_env DB_HOST)}"
DB_PORT="${DB_PORT:-$(leer_env DB_PORT)}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-3306}"

if [ -z "$DB_NAME" ] || [ -z "$DB_USER" ]; then
  echo "Faltan DB_NAME/DB_USER — defínelas en backend/.env o en el entorno." >&2
  echo "Este script respalda vía mysqldump con variables discretas; si la app se conecta con DATABASE_URL, DB_NAME/DB_USER igual hacen falta aquí." >&2
  exit 1
fi

mkdir -p "$DIR_RESPALDOS"

MARCA_TIEMPO="$(date +%Y%m%d_%H%M%S)"
ARCHIVO="$DIR_RESPALDOS/scs_${MARCA_TIEMPO}.sql.gz"

# MYSQL_PWD en vez de -p en el comando: -p deja la contraseña visible en la
# lista de procesos (`ps aux`) para cualquier otro usuario del servidor
# mientras el dump corre.
MYSQL_PWD="$DB_PASSWORD" mysqldump \
  --single-transaction \
  --routines \
  --triggers \
  -u "$DB_USER" \
  -h "$DB_HOST" \
  -P "$DB_PORT" \
  "$DB_NAME" | gzip > "$ARCHIVO"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Respaldo creado: $ARCHIVO ($(du -h "$ARCHIVO" | cut -f1))"

BORRADOS=$(find "$DIR_RESPALDOS" -name 'scs_*.sql.gz' -mtime "+$RETENCION_DIAS" -print -delete | wc -l)
if [ "$BORRADOS" -gt 0 ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $BORRADOS respaldo(s) con más de $RETENCION_DIAS días purgado(s)."
fi
