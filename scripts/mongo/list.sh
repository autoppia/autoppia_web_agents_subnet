#!/bin/bash

# Cargar variables de entorno ignorando comentarios y líneas vacías
export $(grep -v '^#' .env | grep -v '^$' | xargs)

# Verificar si MONGODB_URL está definido
if [ -z "$MONGODB_URL" ]; then
  echo "Error: MONGODB_URL no está configurado en el archivo .env"
  exit 1
fi

# Verificar si el contenedor de MongoDB está corriendo
if ! sudo docker ps --format '{{.Names}}' | grep -q '^mongodb$'; then
  echo "Error: El contenedor 'mongodb' no está en ejecución."
  exit 1
fi

# Ejecutar la consulta dentro del contenedor de Docker
sudo docker exec -it mongodb mongosh --eval '
db.getMongo().getDBNames().forEach(function(dbName) {
  if (["admin", "config", "local"].indexOf(dbName) === -1) {
    print("Database: " + dbName);
    var dbInstance = db.getSiblingDB(dbName);
    dbInstance.getCollectionNames().forEach(function(coll) {
      var count = dbInstance.getCollection(coll).countDocuments();
      print("  Collection: " + coll + " -> Count: " + count);
    });
  }
});
'
