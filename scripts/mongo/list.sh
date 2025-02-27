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

# Verificar si mongo está instalado
if ! command -v mongo &> /dev/null; then
  echo "Error: mongo no está instalado o no está en el PATH"
  exit 1
fi

# Ejecutar la consulta en MongoDB
mongo "$MONGODB_URL" --quiet --eval '
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
