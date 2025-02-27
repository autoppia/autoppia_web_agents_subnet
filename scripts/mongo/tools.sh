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
  echo "  test-connection            Test the MongoDB connection"
  echo "  help, --help, -h           Show this help message"
  echo ""
  exit 1
}

# Extract authentication information from MONGODB_URL
extract_mongo_auth() {
  # Check if MONGODB_URL is set
  if [ -z "$MONGODB_URL" ]; then
    echo "Error: MONGODB_URL not defined in .env file"
    exit 1
  fi
  
  # Parse the MongoDB connection string
  if [[ "$MONGODB_URL" =~ mongodb://([^:]+):([^@]+)@([^/]+)/(.+)(\?.+)? ]]; then
    MONGO_USER="${BASH_REMATCH[1]}"
    MONGO_PASS="${BASH_REMATCH[2]}"
    MONGO_HOST="${BASH_REMATCH[3]}"
    MONGO_DB="${BASH_REMATCH[4]%%\?*}"  # Remove query parameters if any
    
    # For security, mask the password in logs
    echo "Parsed connection info:"
    echo "- User: $MONGO_USER"
    echo "- Host: $MONGO_HOST"
    echo "- Database: $MONGO_DB"
    echo "- Password: [HIDDEN]"
    
    # Export variables for mongosh to use
    export MONGO_USER
    export MONGO_PASS
    export MONGO_HOST
    export MONGO_DB
  else
    echo "Error: Could not parse MongoDB connection string"
    echo "Expected format: mongodb://username:password@host/database"
    exit 1
  fi
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

# Run MongoDB command with direct login credentials
run_mongo_command() {
  local DB="$1"
  local QUERY="$2"
  find_mongo_container
  extract_mongo_auth
  
  echo "Executing MongoDB query..."
  
  # Try different auth methods, one at a time
  
  # Method 1: Using command line auth parameters
  echo "Trying authentication method 1..."
  docker exec -it "$MONGO_CONTAINER" mongosh --quiet \
    --username "$MONGO_USER" \
    --password "$MONGO_PASS" \
    --authenticationDatabase admin \
    --host "$MONGO_HOST" \
    --db "$DB" \
    --eval "$QUERY"
  
  # If the first method fails, try the second
  if [ $? -ne 0 ]; then
    echo "Method 1 failed, trying authentication method 2..."
    docker exec -it "$MONGO_CONTAINER" bash -c "MONGO_USER='$MONGO_USER' MONGO_PASS='$MONGO_PASS' mongosh --quiet --host '$MONGO_HOST' --username '$MONGO_USER' --password '$MONGO_PASS' --authenticationDatabase admin --db '$DB' --eval '$QUERY'"
  fi
  
  # If the second method fails, try the direct connection string
  if [ $? -ne 0 ]; then
    echo "Method 2 failed, trying authentication method 3..."
    docker exec -it "$MONGO_CONTAINER" bash -c "mongosh '$MONGODB_URL' --quiet --eval '$QUERY'"
  fi
}

# List all databases and collections
list_databases() {
  QUERY='
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
  run_mongo_command "admin" "$QUERY"
}

# Drop all collections in a database
drop_database() {
  if [ -z "$1" ]; then
    echo "Error: Database name required"
    echo "Usage: $0 drop-db <db_name>"
    exit 1
  fi
  
  DB_NAME=$1
  
  echo "Warning: This will drop all collections in database '$DB_NAME'"
  read -p "Are you sure you want to continue? (y/n): " confirm
  if [ "$confirm" != "y" ]; then
    echo "Operation cancelled"
    exit 0
  fi
  
  QUERY="
  db.getCollectionNames().forEach(function(coll) {
    print('Dropping collection: ' + coll);
    db.getCollection(coll).drop();
  });
  "
  run_mongo_command "$DB_NAME" "$QUERY"
  
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
  
  echo "Warning: This will drop collection '$COLLECTION' from database '$DB_NAME'"
  read -p "Are you sure you want to continue? (y/n): " confirm
  if [ "$confirm" != "y" ]; then
    echo "Operation cancelled"
    exit 0
  fi
  
  QUERY="
  print('Dropping collection: $COLLECTION');
  db.getCollection('$COLLECTION').drop();
  "
  run_mongo_command "$DB_NAME" "$QUERY"
  
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
  
  echo "Viewing up to $N documents from collection '$COLLECTION' in database '$DB_NAME'..."
  
  QUERY="
  db.getCollection('$COLLECTION').find({}).limit($N).pretty();
  "
  run_mongo_command "$DB_NAME" "$QUERY"
}

# Test connection
test_connection() {
  echo "Testing MongoDB connection..."
  extract_mongo_auth
  find_mongo_container
  
  echo "Trying to connect to MongoDB..."
  
  # Try multiple connection methods
  echo "Testing connection method 1..."
  docker exec -it "$MONGO_CONTAINER" mongosh --quiet \
    --username "$MONGO_USER" \
    --password "$MONGO_PASS" \
    --authenticationDatabase admin \
    --host "$MONGO_HOST" \
    --eval 'db.runCommand({ping: 1})'
  
  if [ $? -eq 0 ]; then
    echo "Connection successful with method 1!"
    return 0
  fi
  
  echo "Testing connection method 2..."
  docker exec -it "$MONGO_CONTAINER" bash -c "MONGO_USER='$MONGO_USER' MONGO_PASS='$MONGO_PASS' mongosh --quiet --host '$MONGO_HOST' --username '$MONGO_USER' --password '$MONGO_PASS' --authenticationDatabase admin --eval 'db.runCommand({ping: 1})'"
  
  if [ $? -eq 0 ]; then
    echo "Connection successful with method 2!"
    return 0
  fi
  
  echo "Testing connection method 3..."
  docker exec -it "$MONGO_CONTAINER" bash -c "mongosh '$MONGODB_URL' --quiet --eval 'db.runCommand({ping: 1})'"
  
  if [ $? -eq 0 ]; then
    echo "Connection successful with method 3!"
    return 0
  fi
  
  echo "All connection methods failed."
  echo "Please check your MongoDB credentials and connection string."
  exit 1
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
  "test-connection")
    test_connection
    ;;
  "help"|"--help"|"-h")
    show_usage
    ;;
  *)
    show_usage
    ;;
esac

exit 0