#!/bin/bash

# Cargar variables de entorno de manera segura
set -a
if [ -f .env ]; then
  source <(grep -v '^#' .env | grep -v '^$')
fi
set +a

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
  echo "Using MongoDB container: $MONGO_CONTAINER"
  return 0
}

# Extract credentials from MongoDB URL if present
extract_credentials() {
  # Check if MONGODB_URL exists and has credentials
  if [ -z "$MONGODB_URL" ]; then
    echo "Warning: MONGODB_URL not set in .env file"
    echo "Assuming connection doesn't require authentication"
    MONGO_AUTH=""
    return
  fi
  
  # Print connection string information (without showing the actual password)
  echo "Using connection string from environment"
  
  # Extract username and password if they exist
  if [[ "$MONGODB_URL" =~ mongodb://([^:]+):([^@]+)@(.+) ]]; then
    MONGO_USER="${BASH_REMATCH[1]}"
    MONGO_PASS="${BASH_REMATCH[2]}"
    MONGO_AUTH="--username $MONGO_USER --password $MONGO_PASS --authenticationDatabase admin"
    echo "Authentication: Using credentials from connection string"
  else
    echo "Authentication: No credentials found in connection string"
    MONGO_AUTH=""
  fi
}

# List all databases and collections
list_databases() {
  find_mongo_container
  extract_credentials
  
  echo "Listing all databases and collections..."
  
  # First check if we're using authentication
  if [ -n "$MONGO_AUTH" ]; then
    # Use the extracted auth parameters
    docker exec "$MONGO_CONTAINER" mongosh --quiet $MONGO_AUTH --eval '
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
  else
    # Try using the full connection string directly
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
  fi
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
  extract_credentials
  
  echo "Warning: This will drop all collections in database '$DB_NAME'"
  read -p "Are you sure you want to continue? (y/n): " confirm
  if [ "$confirm" != "y" ]; then
    echo "Operation cancelled"
    exit 0
  fi
  
  if [ -n "$MONGO_AUTH" ]; then
    docker exec "$MONGO_CONTAINER" mongosh $MONGO_AUTH --eval "
    db = db.getSiblingDB('$DB_NAME');
    db.getCollectionNames().forEach(function(coll) {
      print('Dropping collection: ' + coll);
      db.getCollection(coll).drop();
    });
    "
  else
    docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --eval "
    db = db.getSiblingDB('$DB_NAME');
    db.getCollectionNames().forEach(function(coll) {
      print('Dropping collection: ' + coll);
      db.getCollection(coll).drop();
    });
    "
  fi
  
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
  extract_credentials
  
  echo "Warning: This will drop collection '$COLLECTION' from database '$DB_NAME'"
  read -p "Are you sure you want to continue? (y/n): " confirm
  if [ "$confirm" != "y" ]; then
    echo "Operation cancelled"
    exit 0
  fi
  
  if [ -n "$MONGO_AUTH" ]; then
    docker exec "$MONGO_CONTAINER" mongosh $MONGO_AUTH --eval "
    db = db.getSiblingDB('$DB_NAME');
    print('Dropping collection: $COLLECTION');
    db.getCollection('$COLLECTION').drop();
    "
  else
    docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --eval "
    db = db.getSiblingDB('$DB_NAME');
    print('Dropping collection: $COLLECTION');
    db.getCollection('$COLLECTION').drop();
    "
  fi
  
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
  extract_credentials
  
  echo "Viewing up to $N documents from collection '$COLLECTION' in database '$DB_NAME'..."
  
  if [ -n "$MONGO_AUTH" ]; then
    docker exec "$MONGO_CONTAINER" mongosh $MONGO_AUTH --eval "
    db = db.getSiblingDB('$DB_NAME');
    db.getCollection('$COLLECTION').find({}).limit($N).pretty();
    "
  else
    docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --eval "
    db = db.getSiblingDB('$DB_NAME');
    db.getCollection('$COLLECTION').find({}).limit($N).pretty();
    "
  fi
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