#!/bin/bash
if [ -z "$1" ] || [ -z "$2" ]; then
  echo "Usage: $0 <db_name> <collection_name>"
  exit 1
fi

DB_NAME=$1
COLLECTION=$2

sudo docker exec -it mongodb mongosh --eval "db = db.getSiblingDB('$DB_NAME'); print('Dropping collection: $COLLECTION'); db.getCollection('$COLLECTION').drop();"
