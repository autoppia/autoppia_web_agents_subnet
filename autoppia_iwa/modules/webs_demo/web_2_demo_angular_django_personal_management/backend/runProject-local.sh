#!/bin/bash

# Crea un entorno virtual (si aún no existe)
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activa el entorno virtual
source venv/bin/activate

# Renombra env.example a .env si no existe
if [ ! -f ".env" ]; then
    cp env.example .env
fi

# Leer el nombre de la base de datos del usuario
read -p "Ingresa el nombre de la base de datos (presiona Enter para usar 'bd_presentation' por defecto): " DATABASE_NAME
DATABASE_NAME=${DATABASE_NAME:-bd_presentation}  # Usa 'bd_presentation' por defecto si no se proporciona

# Configuración de la base de datos
export PGUSER=postgres
export PGPASSWORD=postgres
export PGHOST=localhost
export PGPORT=5432
export PGDATABASE=$DATABASE_NAME

# Verifica si la base de datos existe
if psql -lqt | cut -d \| -f 1 | grep -qw $PGDATABASE; then
    # Si la base de datos existe, elimínala
    dropdb $PGDATABASE
fi

# Crea la base de datos
createdb $PGDATABASE

# Actualiza la URL de la base de datos en el archivo .env
sed -i "s/^DATABASE_URL=.*/DATABASE_URL=postgres:\/\/$PGUSER:$PGPASSWORD@$PGHOST:$PGPORT\/$PGDATABASE/" .env

# Instala los requisitos
pip install -r requirements/local.txt

# Realiza migraciones
python manage.py makemigrations
python manage.py migrate

# Inicia el servidor de desarrollo en el puerto 3000
python manage.py runserver 3000
