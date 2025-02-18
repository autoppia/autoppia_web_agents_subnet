#!/bin/bash
sudo docker exec -it mongodb mongosh --eval 'db.getMongo().getDBNames().forEach(function(dbName) {
  if (["admin", "config", "local"].indexOf(dbName) === -1) {
    print("Database: " + dbName);
    var dbInstance = db.getSiblingDB(dbName);
    dbInstance.getCollectionNames().forEach(function(coll) {
      var count = dbInstance.getCollection(coll).countDocuments();
      print("  Collection: " + coll + " -> Count: " + count);
    });
  }
});'
