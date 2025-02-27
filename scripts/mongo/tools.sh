#!/bin/bash

# Cargar variables de entorno de manera segura
set -a
if [ -f .env ]; then
  source <(grep -v '^#' .env | grep -v '^$')
fi
set +a

# Verificar si MONGODB_URL está definido
if [ -z "$MONGODB_URL" ]; then
  echo "Error: MONGODB_URL no está configurado en el archivo .env"
  exit 1
fi

# Function to show usage
show_usage() {
  echo "MongoDB Management Script"
  echo "-------------------------"
  echo "Usage: $0 [option] [arguments]"
  echo ""
  echo "Options:"
  echo "  list                       List all databases and collections"
  echo "  drop-db <db_name>          Drop all collections in a database"
  echo "  drop-collection <db_name> <collection_name>   Drop a specific collection"
  echo "  view <db_name> <collection_name> [num_docs]   View documents in a collection"
  echo "  help, --help, -h           Show this help message"
  echo ""
  exit 1
}

# Find MongoDB container
find_mongo_container() {
  MONGO_CONTAINER=$(docker ps --filter "ancestor=mongo:latest" --format "{{.ID}}")
  if [ -z "$MONGO_CONTAINER" ]; then
    # Try alternative way to find mongo container
    MONGO_CONTAINER=$(docker ps --filter "name=mongodb" --format "{{.ID}}")
    if [ -z "$MONGO_CONTAINER" ]; then
      echo "Error: No MongoDB container found"
      exit 1
    fi
  fi
  return 0
}

# List all databases and collections
list_databases() {
  find_mongo_container
  
  echo "Listing all databases and collections..."
  docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --quiet --eval '
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
}

# Drop all collections in a database
drop_database() {
  if [ -z "$1" ]; then
    echo "Error: Database name required"
    echo "Usage: $0 drop-db <db_name>"
    exit 1
  fi
  
  DB_NAME=$1
  find_mongo_container
  
  echo "Warning: This will drop all collections in database '$DB_NAME'"
  read -p "Are you sure you want to continue? (y/n): " confirm
  if [ "$confirm" != "y" ]; then
    echo "Operation cancelled"
    exit 0
  fi
  
  docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --eval "
  db = db.getSiblingDB('$DB_NAME');
  db.getCollectionNames().forEach(function(coll) {
    print('Dropping collection: ' + coll);
    db.getCollection(coll).drop();
  });
  "
  
  echo "All collections in database '$DB_NAME' have been dropped"
}

# Drop a specific collection
drop_collection() {
  if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Error: Database name and collection name required"
    echo "Usage: $0 drop-collection <db_name> <collection_name>"
    exit 1
  fi
  
  DB_NAME=$1
  COLLECTION=$2
  find_mongo_container
  
  echo "Warning: This will drop collection '$COLLECTION' from database '$DB_NAME'"
  read -p "Are you sure you want to continue? (y/n): " confirm
  if [ "$confirm" != "y" ]; then
    echo "Operation cancelled"
    exit 0
  fi
  
  docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --eval "
  db = db.getSiblingDB('$DB_NAME');
  print('Dropping collection: $COLLECTION');
  db.getCollection('$COLLECTION').drop();
  "
  
  echo "Collection '$COLLECTION' has been dropped from database '$DB_NAME'"
}

# View documents in a collection
view_collection() {
  if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Error: Database name and collection name required"
    echo "Usage: $0 view <db_name> <collection_name> [num_docs]"
    exit 1
  fi
  
  DB_NAME=$1
  COLLECTION=$2
  N=${3:-10}  # Default to 10 documents if not specified
  find_mongo_container
  
  echo "Viewing up to $N documents from collection '$COLLECTION' in database '$DB_NAME'..."
  docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --eval "
  db = db.getSiblingDB('$DB_NAME');
  db.getCollection('$COLLECTION').find({}).limit($N).pretty();
  "
}

# Main script logic
if [ $# -lt 1 ]; then
  show_usage
fi

case "$1" in
  "list")
    list_databases
    ;;
  "drop-db")
    drop_database "$2"
    ;;
  "drop-collection")
    drop_collection "$2" "$3"
    ;;
  "view")
    view_collection "$2" "$3" "$4"
    ;;
  "help"|"--help"|"-h")
    show_usage
    ;;
  *)
    show_usage
    ;;
esac

exit 0