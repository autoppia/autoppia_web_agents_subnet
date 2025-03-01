#!/bin/bash
# MongoDB Tools Script - Using the .env file from project root

# Find project root path - ensures we're using the correct .env file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

echo "[INFO] Using .env file at: $ENV_FILE"

# Check if .env file exists
if [ ! -f "$ENV_FILE" ]; then
  echo "Error: .env file not found at $ENV_FILE"
  exit 1
fi

# Extract MongoDB URL directly from root .env file - handling quotes properly
MONGODB_URL=$(grep -E "^MONGODB_URL=" "$ENV_FILE" | sed 's/^MONGODB_URL=//;s/^"//;s/"$//' || true)

# Verify if MONGODB_URL is defined
if [ -z "$MONGODB_URL" ]; then
  echo "Error: MONGODB_URL is not set in the .env file at $ENV_FILE"
  exit 1
fi

# Show first part of connection string for debugging (hide password)
CONNECTION_PREFIX=$(echo "$MONGODB_URL" | grep -o 'mongodb://[^:]*' || echo "Connection string extraction failed")
echo "[DEBUG] Connection string starts with: $CONNECTION_PREFIX"

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
  echo "  interactive <db_name> <collection_name>       Interactively review and delete documents"
  echo "  help, --help, -h           Show this help message"
  echo ""
  exit 1
}

# Find MongoDB container
find_mongo_container() {
  MONGO_CONTAINER=$(docker ps --filter "ancestor=mongo:latest" --format "{{.ID}}" 2>/dev/null || true)
  
  # Verify if container was found, try alternative method
  if [ -z "$MONGO_CONTAINER" ]; then
    MONGO_CONTAINER=$(docker ps --filter "name=mongodb" --format "{{.ID}}" 2>/dev/null || true)
    if [ -z "$MONGO_CONTAINER" ]; then
      echo "Error: No MongoDB container found"
      exit 1
    fi
  fi
  
  echo "Using MongoDB container: $MONGO_CONTAINER"
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
  
  docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --quiet --eval "
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
  
  docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --quiet --eval "
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
  
  docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --quiet --eval "
  db = db.getSiblingDB('$DB_NAME');
  db.getCollection('$COLLECTION').find({}).limit($N).pretty();
  "
}

# Interactively review and delete documents
interactive_review() {
  if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Error: Database name and collection name required"
    echo "Usage: $0 interactive <db_name> <collection_name>"
    exit 1
  fi
  
  DB_NAME=$1
  COLLECTION=$2
  find_mongo_container
  
  echo "Starting interactive review for collection '$COLLECTION' in database '$DB_NAME'..."
  echo "For each document, you'll be asked if you want to delete it."
  echo "----------------------------------------"
  
  # First, get the total count of documents
  TOTAL_DOCS=$(docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --quiet --eval "
    db = db.getSiblingDB('$DB_NAME');
    db.getCollection('$COLLECTION').countDocuments({});
  ")
  
  if [ "$TOTAL_DOCS" -eq 0 ]; then
    echo "Collection is empty. Nothing to review."
    return
  fi
  
  echo "Total documents: $TOTAL_DOCS"
  
  # Process documents in batches for better performance
  BATCH_SIZE=1
  COUNTER=0
  DELETED=0
  KEPT=0
  
  while [ $COUNTER -lt $TOTAL_DOCS ] && [ $COUNTER -lt 1000 ]; do  # Limit to 1000 for safety
    # Get a single document
    DOCUMENT=$(docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --quiet --eval "
      db = db.getSiblingDB('$DB_NAME');
      db.getCollection('$COLLECTION').find({}).skip($COUNTER).limit(1).pretty();
    ")
    
    if [ -z "$DOCUMENT" ]; then
      echo "No more documents found."
      break
    fi
    
    COUNTER=$((COUNTER + 1))
    
    # Get document ID for deletion
    DOC_ID=$(docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --quiet --eval "
      db = db.getSiblingDB('$DB_NAME');
      var doc = db.getCollection('$COLLECTION').find({}).skip($((COUNTER - 1))).limit(1).toArray()[0];
      printjson(doc._id);
    ")
    
    # Display the document (only first 10 lines)
    echo -e "\nDocument $COUNTER of $TOTAL_DOCS:"
    echo "$DOCUMENT" | head -n 10
    echo "... (truncated, showing first 10 lines only)"
    
    # Ask for user input
    read -p "Delete this document? (y/n/q to quit): " USER_RESPONSE
    
    if [ "$USER_RESPONSE" = "y" ]; then
      # Delete the document
      docker exec "$MONGO_CONTAINER" mongosh "$MONGODB_URL" --quiet --eval "
        db = db.getSiblingDB('$DB_NAME');
        db.getCollection('$COLLECTION').deleteOne({ _id: $DOC_ID });
      "
      echo "Document deleted."
      DELETED=$((DELETED + 1))
      # Don't increment counter when deleting, as the next document will shift into this position
      COUNTER=$((COUNTER - 1))
    elif [ "$USER_RESPONSE" = "q" ]; then
      echo "Review aborted by user."
      break
    else
      echo "Document kept."
      KEPT=$((KEPT + 1))
    fi
  done
  
  echo -e "\n----------------------------------------"
  echo "Review summary: $COUNTER documents processed, $DELETED deleted, $KEPT kept."
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
  "interactive")
    interactive_review "$2" "$3"
    ;;
  "help"|"--help"|"-h")
    show_usage
    ;;
  *)
    show_usage
    ;;
esac

exit 0