#!/bin/bash
if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
  echo "Usage: $0 <db_name> <collection_name> <number_of_documents>"
  exit 1
fi

DB_NAME=$1
COLLECTION=$2
N=$3

sudo docker exec -it mongodb mongosh --eval "db = db.getSiblingDB('$DB_NAME'); db.getCollection('$COLLECTION').find({}).limit($N).pretty();"
