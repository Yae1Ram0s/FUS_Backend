#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input

if [[ -n "${INITIAL_TEST_PASSWORD:-}" ]]; then
  python manage.py cargar_datos_iniciales --password "$INITIAL_TEST_PASSWORD"
fi
