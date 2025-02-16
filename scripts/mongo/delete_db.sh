#!/bin/bash
if [ -z "$1" ]; then
  echo "Usage: $0 <db_name>"
  exit 1
fi

DB_NAME=$1

sudo docker exec -it mongodb mongosh --eval "db.getSiblingDB('$DB_NAME').dropDatabase()"
