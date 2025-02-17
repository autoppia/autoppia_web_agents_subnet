#!/bin/bash
# entrypoint.sh

echo "Entrando al entrypoint.sh..."
# 1. Ejecutar migraciones como es un SQLITE (crea/actualiza tablas en SQLite).
python manage.py makemigrations --noinput
python manage.py migrate --noinput

# 2. (Opcional) Si quieres "seedear" tu DB, aquí podrías hacer:
python manage.py seed_db
echo "seed creada en la base datos..."

# 3. Finalmente, arrancar Gunicorn.
exec gunicorn --bind 0.0.0.0:8002 config.wsgi:application
