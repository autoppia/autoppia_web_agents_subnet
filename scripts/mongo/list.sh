#!/bin/bash
sudo docker exec -it mongodb mongosh --eval "db.getMongo().getDBNames().forEach(function(dbName) { if (['admin','config','local'].indexOf(dbName) === -1) { print('Database: ' + dbName); printjson(db.getSiblingDB(dbName).getCollectionNames()); } })"
