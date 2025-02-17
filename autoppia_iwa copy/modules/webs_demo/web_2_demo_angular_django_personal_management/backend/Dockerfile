FROM python:3.10-slim

# Evitar archivos .pyc
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Step 4: Copy the requirements files to the container
COPY requirements/*.txt ./

# Step 5: Install the required Python dependencies
RUN pip install --no-cache-dir -r production.txt


# Copiamos todo el código Django al contenedor
COPY . /app/

# Copiar nuestro script de entrypoint y darle permisos de ejecución. Lo ponemos fuer adel app para poder usar el bind mount
COPY entrypoint.sh /docker-entrypoint.d/entrypoint.sh
RUN chmod +x /docker-entrypoint.d/entrypoint.sh
# Reemplazamos CMD con un ENTRYPOINT
ENTRYPOINT ["/docker-entrypoint.d/entrypoint.sh"]


EXPOSE 8002
