#!/bin/bash

# Cargar variables de entorno de manera segura
set -a
source <(grep -v '^#' .env | grep -v '^$')
set +a

# Verificar si MONGODB_URL está definido
if [ -z "$MONGODB_URL" ]; then
  echo "Error: MONGODB_URL no está configurado en el archivo .env"
  exit 1
fi

# Obtener el ID o nombre del contenedor de MongoDB
MONGO_CONTAINER=$(docker ps --filter "ancestor=mongo:latest" --format "{{.ID}}")

# Verificar si se encontró un contenedor en ejecución
if [ -z "$MONGO_CONTAINER" ]; then
  echo "Error: No se encontró un contenedor en ejecución con la imagen mongo:latest"
  exit 1
fi

# Ejecutar la consulta en MongoDB dentro del contenedor
docker exec "$MONGO_CONTAINER" mongo "$MONGODB_URL" --quiet --eval '
db.adminCommand("listDatabases").databases.forEach(function(dbInfo) {
  if (["admin", "config", "local"].indexOf(dbInfo.name) === -1) {
    print("Database: " + dbInfo.name);
    var dbInstance = db.getSiblingDB(dbInfo.name);
    dbInstance.getCollectionNames().forEach(function(coll) {
      var count = dbInstance.getCollection(coll).count();
      print("  Collection: " + coll + " -> Count: " + count);
    });
  }
});
'
