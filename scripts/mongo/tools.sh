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
  echo "  direct-connect             Connect directly to MongoDB shell"
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

# Run MongoDB command inside the container directly
run_inside_container() {
  local COMMAND="$1"
  find_mongo_container
  
  echo "Executing command inside MongoDB container..."
  docker exec -it "$MONGO_CONTAINER" bash -c "$COMMAND"
}

# List all databases and collections using direct mongo commands
list_databases() {
  # First connect to mongo without authentication to see if that works
  COMMAND="mongosh --quiet --eval '
  try {
    db.adminCommand(\"listDatabases\").databases.forEach(function(dbInfo) {
      if ([\"admin\", \"config\", \"local\"].indexOf(dbInfo.name) === -1) {
        print(\"Database: \" + dbInfo.name);
        var dbInstance = db.getSiblingDB(dbInfo.name);
        dbInstance.getCollectionNames().forEach(function(coll) {
          var count = dbInstance.getCollection(coll).count();
          print(\"  Collection: \" + coll + \" -> Count: \" + count);
        });
      }
    });
  } catch (e) {
    print(\"Error: \" + e);
    
    // If authentication is required, try to use environment variables
    if (e.message.includes(\"Authentication\")) {
      print(\"Trying to use environment variables for authentication...\");
      
      // Try with explicit credentials that might be found in env vars
      if (process.env.MONGO_INITDB_ROOT_USERNAME && process.env.MONGO_INITDB_ROOT_PASSWORD) {
        print(\"Found MongoDB credentials in environment. Attempting login...\");
        
        // Try to authenticate using these credentials
        var adminDB = db.getSiblingDB(\"admin\");
        try {
          adminDB.auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD);
          print(\"Authentication successful with environment credentials!\");
          
          // Now list databases
          db.adminCommand(\"listDatabases\").databases.forEach(function(dbInfo) {
            if ([\"admin\", \"config\", \"local\"].indexOf(dbInfo.name) === -1) {
              print(\"Database: \" + dbInfo.name);
              var dbInstance = db.getSiblingDB(dbInfo.name);
              dbInstance.getCollectionNames().forEach(function(coll) {
                var count = dbInstance.getCollection(coll).count();
                print(\"  Collection: \" + coll + \" -> Count: \" + count);
              });
            }
          });
        } catch (authError) {
          print(\"Authentication failed with environment credentials: \" + authError);
        }
      } else {
        print(\"No MongoDB credentials found in environment.\");
        print(\"Please check if MongoDB is configured with authentication.\");
        print(\"If so, you may need to set MONGO_INITDB_ROOT_USERNAME and MONGO_INITDB_ROOT_PASSWORD\");
        print(\"in your Docker container or provide them in your connection string.\");
      }
    }
  }
  '"

  run_inside_container "$COMMAND"
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
  
  COMMAND="mongosh --quiet --eval '
  try {
    db = db.getSiblingDB(\"$DB_NAME\");
    db.getCollectionNames().forEach(function(coll) {
      print(\"Dropping collection: \" + coll);
      db.getCollection(coll).drop();
    });
  } catch (e) {
    print(\"Error: \" + e);
    
    // If authentication is required, try to use environment variables
    if (e.message.includes(\"Authentication\")) {
      print(\"Trying to use environment variables for authentication...\");
      
      // Try with explicit credentials that might be found in env vars
      if (process.env.MONGO_INITDB_ROOT_USERNAME && process.env.MONGO_INITDB_ROOT_PASSWORD) {
        print(\"Found MongoDB credentials in environment. Attempting login...\");
        
        // Try to authenticate using these credentials
        var adminDB = db.getSiblingDB(\"admin\");
        try {
          adminDB.auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD);
          print(\"Authentication successful with environment credentials!\");
          
          // Now drop collections
          db = db.getSiblingDB(\"$DB_NAME\");
          db.getCollectionNames().forEach(function(coll) {
            print(\"Dropping collection: \" + coll);
            db.getCollection(coll).drop();
          });
        } catch (authError) {
          print(\"Authentication failed with environment credentials: \" + authError);
        }
      }
    }
  }
  '"
  
  run_inside_container "$COMMAND"
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
  
  COMMAND="mongosh --quiet --eval '
  try {
    db = db.getSiblingDB(\"$DB_NAME\");
    print(\"Dropping collection: $COLLECTION\");
    db.getCollection(\"$COLLECTION\").drop();
  } catch (e) {
    print(\"Error: \" + e);
    
    // If authentication is required, try to use environment variables
    if (e.message.includes(\"Authentication\")) {
      print(\"Trying to use environment variables for authentication...\");
      
      // Try with explicit credentials that might be found in env vars
      if (process.env.MONGO_INITDB_ROOT_USERNAME && process.env.MONGO_INITDB_ROOT_PASSWORD) {
        print(\"Found MongoDB credentials in environment. Attempting login...\");
        
        // Try to authenticate using these credentials
        var adminDB = db.getSiblingDB(\"admin\");
        try {
          adminDB.auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD);
          print(\"Authentication successful with environment credentials!\");
          
          // Now drop the collection
          db = db.getSiblingDB(\"$DB_NAME\");
          print(\"Dropping collection: $COLLECTION\");
          db.getCollection(\"$COLLECTION\").drop();
        } catch (authError) {
          print(\"Authentication failed with environment credentials: \" + authError);
        }
      }
    }
  }
  '"
  
  run_inside_container "$COMMAND"
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
  
  COMMAND="mongosh --quiet --eval '
  try {
    db = db.getSiblingDB(\"$DB_NAME\");
    db.getCollection(\"$COLLECTION\").find({}).limit($N).pretty();
  } catch (e) {
    print(\"Error: \" + e);
    
    // If authentication is required, try to use environment variables
    if (e.message.includes(\"Authentication\")) {
      print(\"Trying to use environment variables for authentication...\");
      
      // Try with explicit credentials that might be found in env vars
      if (process.env.MONGO_INITDB_ROOT_USERNAME && process.env.MONGO_INITDB_ROOT_PASSWORD) {
        print(\"Found MongoDB credentials in environment. Attempting login...\");
        
        // Try to authenticate using these credentials
        var adminDB = db.getSiblingDB(\"admin\");
        try {
          adminDB.auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD);
          print(\"Authentication successful with environment credentials!\");
          
          // Now view the collection
          db = db.getSiblingDB(\"$DB_NAME\");
          db.getCollection(\"$COLLECTION\").find({}).limit($N).pretty();
        } catch (authError) {
          print(\"Authentication failed with environment credentials: \" + authError);
        }
      }
    }
  }
  '"
  
  run_inside_container "$COMMAND"
}

# Direct connect to MongoDB shell
direct_connect() {
  find_mongo_container
  echo "Connecting directly to MongoDB shell..."
  docker exec -it "$MONGO_CONTAINER" mongosh
}

# Test MongoDB container environment variables
test_connection() {
  find_mongo_container
  echo "Testing MongoDB environment variables inside the container..."
  
  COMMAND="bash -c 'echo \"MongoDB Environment Variables:\" && \
    echo \"MONGO_INITDB_ROOT_USERNAME: \$MONGO_INITDB_ROOT_USERNAME\" && \
    echo \"MONGO_INITDB_ROOT_PASSWORD: [Hidden for security]\" && \
    echo \"Trying to connect with mongosh...\" && \
    mongosh --eval \"try { db.adminCommand({ping: 1}); print(\\\"Connection successful!\\\"); } catch(e) { print(\\\"Connection failed: \\\" + e); }\"'"
  
  run_inside_container "$COMMAND"
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
  "direct-connect")
    direct_connect
    ;;
  "help"|"--help"|"-h")
    show_usage
    ;;
  *)
    show_usage
    ;;
esac

exit 0