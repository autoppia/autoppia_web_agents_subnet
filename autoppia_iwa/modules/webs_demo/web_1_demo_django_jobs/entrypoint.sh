#!/bin/bash
# entrypoint.sh

# 1. Ejecutar migraciones como es un SQLITE (crea/actualiza tablas en SQLite).
python manage.py makemigrations --noinput
python manage.py migrate --noinput

# 2. (Opcional) Si quieres "seedear" tu DB, aquí podrías hacer:
python manage.py seed_db

# 3. Finalmente, arrancar Gunicorn.
exec gunicorn --bind 0.0.0.0:8001 jobs.wsgi:application
