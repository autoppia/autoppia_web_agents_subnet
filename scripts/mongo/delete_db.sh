#!/bin/bash
if [ -z "$1" ]; then
  echo "Usage: $0 <db_name>"
  exit 1
fi

DB_NAME=$1

sudo docker exec -it mongo mongosh --eval "db = db.getSiblingDB('$DB_NAME'); db.getCollectionNames().forEach(function(coll) { print('Dropping collection: ' + coll); db.getCollection(coll).drop(); });"
