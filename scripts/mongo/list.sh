#!/bin/bash

export $(grep -v '^#' .env | xargs)

if [ -z "$MONGODB_URL" ]; then
  echo "Error: MONGODB_URL is not set in the .env file"
  exit 1
fi

mongosh "$MONGODB_URL" --eval '
db.getMongo().getDBNames().forEach(function(dbName) {
  if (["admin", "config", "local"].indexOf(dbName) === -1) {
    print("Database: " + dbName);
    var dbInstance = db.getSiblingDB(dbName);
    dbInstance.getCollectionNames().forEach(function(coll) {
      var count = dbInstance.getCollection(coll).countDocuments();
      print("  Collection: " + coll + " -> Count: " + count);
    });
  }
});
'
