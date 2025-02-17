from typing import Any, Dict, List, Optional

from pymongo import MongoClient


class BaseMongoRepository:
    """
    A generic repository for performing CRUD operations on a MongoDB collection.
    """

    def __init__(self, mongo_client: MongoClient, db_name: str, collection_name: str):
        """
        Initialize the BaseMongoRepository.

        Args:
            mongo_client (MongoClient): The MongoDB client.
            db_name (str): The name of the database.
            collection_name (str): The name of the collection.
        """
        self.collection = mongo_client[db_name][collection_name]

    # SAVE (CREATE/INSERT)
    def save(self, data: Dict) -> Any:
        """
        Insert a new document into the collection.

        Args:
            data (dict): The document to insert.

        Returns:
            str: The ID of the inserted document.
        """
        result = self.collection.insert_one(data)
        return result

    # UPDATE
    def update(self, query: Dict, update_data: Dict) -> Any:
        """
        Update documents matching a query.

        Args:
            query (dict): The query to filter documents to update.
            update_data (dict): The fields to update.

        Returns:
            int: The number of documents updated.
        """
        result = self.collection.update_many(query, {"$set": update_data})
        return result

    # FIND_ONE
    def find_one(self, query: Dict) -> Any:
        """
        Find a single document matching a query.

        Args:
            query (dict): The query to match a document.

        Returns:
            Optional[dict]: The first document that matches the query, or None if no match.
        """
        return self.collection.find_one(query)

    # FIND_MANY
    def find_many(self, query: Optional[Dict] = None, limit: int = 0) -> List[Any]:
        """
        Find multiple documents matching a query.

        Args:
            query (Optional[dict]): The query to filter documents. Defaults to an empty query.
            limit (int): The maximum number of documents to return. Default is 0 (no limit).

        Returns:
            List[dict]: A list of matching documents.
        """
        query = query or {}
        return list(self.collection.find(query).limit(limit))

    def delete(self, query: Dict) -> Any:
        """
        Delete documents matching a query.

        Args:
            query (dict): The query to filter documents to delete.

        Returns:
            int: The number of documents deleted.
        """
        result = self.collection.delete_many(query)
        return result.deleted_count

    # COUNT
    def count(self, query: Optional[Dict] = None) -> int:
        """
        Count the number of documents matching a query.

        Args:
            query (Optional[dict]): The query to filter documents. Defaults to an empty query.

        Returns:
            int: The number of matching documents.
        """
        query = query or {}
        return self.collection.count_documents(query)

    # EXISTS
    def exists(self, query: Dict) -> bool:
        """
        Check if any document matches the given query.

        Args:
            query (dict): The query to check.

        Returns:
            bool: True if at least one document matches the query, False otherwise.
        """
        return self.collection.count_documents(query, limit=1) > 0
