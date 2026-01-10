"""Qdrant Vector Database wrapper - Stable, cloud-hosted alternative to ChromaDB.

This module provides a Python wrapper around Qdrant's vector database API for
semantic search and similarity-based retrieval. Supports both local in-memory mode
(for development) and cloud-hosted mode with free tier.

Key features:
- Document storage with metadata
- Semantic search with cosine similarity
- Metadata filtering (e.g., by platform type)
- Token ID management (string IDs converted to integers for Qdrant)
- Progress tracking for bulk operations
- Same interface as ChromaDB for easy migration

Benefits of Qdrant over ChromaDB:
- No corruption issues (stateless cloud API vs local SQLite)
- 1GB free tier (10,000+ documents)
- Production-ready infrastructure with SLA
- Better performance with larger datasets
"""

import logging
import os
import hashlib
from typing import List, Dict, Optional, Any, Sequence
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    Condition
)
from sentence_transformers import SentenceTransformer
from src.infrastructure.embedding_singleton import get_embedding_model

logger = logging.getLogger(__name__)


def _string_to_uuid_int(s: str) -> int:
    """Convert string ID to integer for Qdrant (uses MD5 hash).

    Qdrant requires integer IDs for points, but our system uses string IDs.
    This function converts string IDs to deterministic integers using MD5
    hash, ensuring the same string always maps to the same integer.

    Args:
        s: String ID to convert

    Returns:
        Integer ID derived from MD5 hash of the string (first 15 hex digits)
    """
    return int(hashlib.md5(s.encode()).hexdigest()[:15], 16)


class QdrantVectorDB:
    """Qdrant-based vector database for platform and event storage.

    Manages document storage, embedding generation, and semantic search using
    Qdrant. Supports both local in-memory mode (for development) and cloud mode
    (for production with free 1GB tier).

    Attributes:
        collection_name: Name of the Qdrant collection
        embedding_model: SentenceTransformer model instance
        embedding_model_name: Name/path of the embedding model
        embedding_dim: Dimension of embeddings from the model
        client: QdrantClient instance (local or cloud)
    """

    def __init__(
        self,
        collection_name: str = "poc_platforms",
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        local_mode: bool = False,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    ) -> None:
        """
        Initialize Qdrant vector database.

        Initializes embedding model, connects to Qdrant (local or cloud),
        and creates collection if it doesn't exist.

        Args:
            collection_name: Name of the collection (default: "poc_platforms")
            url: Qdrant cloud URL. Defaults to QDRANT_URL env var.
                 Only used if local_mode=False
            api_key: Qdrant API key. Defaults to QDRANT_API_KEY env var.
                     Only used if local_mode=False
            local_mode: If True, use in-memory Qdrant for development/testing.
                       If False, connects to cloud (fallback to local if keys missing)
            embedding_model: SentenceTransformer model name/path
                            (default: "sentence-transformers/all-MiniLM-L6-v2")

        Raises:
            ValueError: If embedding model doesn't return valid dimension
        """
        self.collection_name: str = collection_name
        self.embedding_model_name: str = embedding_model

        # Load embedding model (singleton pattern for memory efficiency)
        logger.info(f"Getting embedding model: {embedding_model}")
        self.embedding_model: SentenceTransformer = get_embedding_model(embedding_model)
        embedding_dim: Optional[int] = self.embedding_model.get_sentence_embedding_dimension()
        if embedding_dim is None:
            raise ValueError("Embedding model did not return a valid dimension")
        self.embedding_dim: int = embedding_dim
        logger.debug(f"Embedding dimension: {self.embedding_dim}")

        # Initialize Qdrant client
        self.client: QdrantClient
        if local_mode:
            logger.info("Initializing Qdrant in local (persistent disk) mode")
            # Use persistent disk storage instead of in-memory for production
            self.client = QdrantClient(path="./qdrant_storage")
        else:
            url = url or os.getenv("QDRANT_URL")
            api_key = api_key or os.getenv("QDRANT_API_KEY")

            if not url or not api_key:
                logger.warning(
                    "QDRANT_URL and QDRANT_API_KEY not set. "
                    "Falling back to local in-memory mode. "
                    "For production, set these environment variables."
                )
                self.client = QdrantClient(":memory:")
            else:
                logger.info(f"Connecting to Qdrant Cloud: {url}")
                self.client = QdrantClient(url=url, api_key=api_key)

        # Create collection if it doesn't exist
        self._setup_collection()

    def _setup_collection(self) -> None:
        """Create collection if it doesn't exist.

        Checks if the collection exists, creates it with the appropriate
        vector configuration if needed, and logs the current state.

        Raises:
            Exception: Logs and re-raises any errors during setup
        """
        try:
            # Check if collection exists
            collections = self.client.get_collections().collections
            collection_exists = any(c.name == self.collection_name for c in collections)

            if not collection_exists:
                logger.info(f"Creating collection: {self.collection_name}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_dim,
                        distance=Distance.COSINE
                    )
                )
                logger.info(f"Collection '{self.collection_name}' created")
            else:
                logger.info(f"Collection '{self.collection_name}' already exists")

            # Get collection info
            info = self.client.get_collection(self.collection_name)
            logger.info(f"Collection ready. Points count: {info.points_count}")

        except Exception as e:
            logger.error(f"Error setting up collection: {e}")
            raise

    def add(
        self,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str]
    ) -> bool:
        """
        Add documents to the collection.

        Generates embeddings for documents and stores them with metadata in Qdrant.
        Uses upsert (insert or update) semantics - if an ID already exists, it is
        replaced. Original string IDs are preserved in the payload.

        Args:
            documents: List of text documents to embed (must match length of metadatas/ids)
            metadatas: List of metadata dictionaries (one per document)
            ids: List of unique string IDs (one per document)

        Returns:
            True if all documents added successfully, False if error occurs

        Example:
            >>> db = QdrantVectorDB(local_mode=True)
            >>> docs = ["Black Girls CODE teaches coding", "Outdoor Afro connects Black people"]
            >>> metas = [{"type": "Tech", "name": "Black Girls CODE"}, {"type": "Outdoor", "name": "Outdoor Afro"}]
            >>> ids = ["bgc_001", "oa_001"]
            >>> db.add(docs, metas, ids)
            True
        """
        try:
            # Generate embeddings
            logger.info(f"Generating embeddings for {len(documents)} documents")
            embeddings = self.embedding_model.encode(
                documents,
                show_progress_bar=len(documents) > 10
            )

            # Create points (convert string IDs to integers)
            points = []
            id_mapping = {}  # Store mapping of original ID to integer ID
            for i, (doc, metadata, doc_id) in enumerate(zip(documents, metadatas, ids)):
                int_id = _string_to_uuid_int(doc_id)
                id_mapping[doc_id] = int_id

                points.append(
                    PointStruct(
                        id=int_id,
                        vector=embeddings[i].tolist(),
                        payload={
                            "document": doc,
                            "original_id": doc_id,  # Store original ID in payload
                            **metadata
                        }
                    )
                )

            # Upsert points (insert or update)
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )

            logger.info(f"Successfully added {len(points)} points to collection")
            return True

        except Exception as e:
            logger.error(f"Error adding documents: {e}")
            return False

    def search(
        self,
        query: str,
        n_results: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> Dict[str, List[Any]]:
        """
        Search for similar documents using semantic similarity.

        Embeds the query and finds the most similar documents using cosine
        similarity. Results are returned in order of similarity (most similar first).
        Optionally filters results by metadata fields.

        Args:
            query: Natural language search query
            n_results: Number of results to return (default: 5)
            filter_dict: Optional metadata filter as dict (e.g., {"type": "Tech"}).
                        All conditions are ANDed together.

        Returns:
            Dictionary with ChromaDB-compatible format:
                - 'ids': [[list of IDs]]
                - 'documents': [[list of document texts]]
                - 'metadatas': [[list of metadata dicts]]
                - 'distances': [[list of similarity scores, lower = more similar]]

        Example:
            >>> db = QdrantVectorDB(local_mode=True)
            >>> results = db.search("tech communities", n_results=3, filter_dict={"type": "Tech"})
            >>> for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
            ...     print(f"{meta['name']}: {doc[:50]}...")
        """
        try:
            # Generate query embedding
            query_embedding = self.embedding_model.encode(query)

            # Build filter if provided
            qdrant_filter = None
            if filter_dict:
                conditions: List[Condition] = []
                for key, value in filter_dict.items():
                    conditions.append(
                        FieldCondition(
                            key=key,
                            match=MatchValue(value=value)
                        )
                    )
                if conditions:
                    qdrant_filter = Filter(must=conditions)

            # Search (use query instead of search for newer qdrant-client)
            results = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding.tolist(),
                limit=n_results,
                query_filter=qdrant_filter
            ).points

            # Format results to match ChromaDB API
            documents = []
            metadatas = []
            distances = []
            ids = []

            for hit in results:
                # Use original_id from payload if available, otherwise use integer ID
                if hit.payload is not None:
                    original_id = hit.payload.get('original_id', str(hit.id))
                    ids.append(original_id)
                    distances.append(hit.score)
                    payload = dict(hit.payload)  # Make a copy
                    documents.append(payload.pop('document', ''))
                    payload.pop('original_id', None)  # Remove original_id from metadata
                    metadatas.append(payload)

            return {
                'ids': [ids],
                'documents': [documents],
                'metadatas': [metadatas],
                'distances': [distances]
            }

        except Exception as e:
            logger.error(f"Error searching: {e}")
            return {
                'ids': [[]],
                'documents': [[]],
                'metadatas': [[]],
                'distances': [[]]
            }

    def get(self, ids: Optional[List[str]] = None) -> Dict[str, List[Any]]:
        """
        Get all documents or documents by specific IDs.

        Retrieves full documents and metadata from the collection. If ids is
        None, retrieves all documents (using pagination). If ids is provided,
        retrieves only those specific documents.

        Args:
            ids: Optional list of string IDs to retrieve. If None, retrieves all.

        Returns:
            Dictionary with keys:
                - 'ids': List of point IDs (integers)
                - 'documents': List of document texts
                - 'metadatas': List of metadata dicts
        """
        try:
            if ids:
                # Get specific points
                results = self.client.retrieve(
                    collection_name=self.collection_name,
                    ids=ids
                )
            else:
                # Get all points (paginated)
                results = []
                offset = None
                while True:
                    batch = self.client.scroll(
                        collection_name=self.collection_name,
                        limit=100,
                        offset=offset
                    )
                    points, offset = batch
                    results.extend(points)
                    if offset is None:
                        break

            # Format results
            documents = []
            metadatas = []
            point_ids = []

            for point in results:
                point_ids.append(point.id)
                if point.payload is not None:
                    payload = point.payload
                    documents.append(payload.pop('document', ''))
                    metadatas.append(payload)

            return {
                'ids': point_ids,
                'documents': documents,
                'metadatas': metadatas
            }

        except Exception as e:
            logger.error(f"Error getting documents: {e}")
            return {
                'ids': [],
                'documents': [],
                'metadatas': []
            }

    def delete(self, ids: List[str]) -> bool:
        """
        Delete documents by their IDs.

        Removes points from the collection. Fails silently if IDs don't exist.

        Args:
            ids: List of string IDs to delete

        Returns:
            True if deletion succeeded (or IDs don't exist), False if error occurs
        """
        try:
            # Qdrant expects a list, explicitly cast for type checker
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=list(ids)
            )
            logger.info(f"Deleted {len(ids)} points")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents: {e}")
            return False

    def count(self) -> int:
        """Get total number of documents in collection.

        Returns:
            Number of points (documents) stored in the collection, or 0 if error
        """
        try:
            info = self.client.get_collection(self.collection_name)
            # Handle Optional[int] return type from points_count
            points_count = info.points_count
            return points_count if points_count is not None else 0
        except Exception as e:
            logger.error(f"Error getting count: {e}")
            return 0

    def clear(self) -> bool:
        """Clear all documents from collection.

        Deletes and recreates the collection. Useful for full resets during
        development or data cleanup.

        Returns:
            True if successful, False if error occurs
        """
        try:
            self.client.delete_collection(self.collection_name)
            self._setup_collection()
            logger.info(f"Collection '{self.collection_name}' cleared and recreated")
            return True
        except Exception as e:
            logger.error(f"Error clearing collection: {e}")
            return False


if __name__ == '__main__':
    # Test Qdrant implementation
    logging.basicConfig(level=logging.INFO)

    print("\n" + "="*70)
    print("TESTING QDRANT VECTOR DB")
    print("="*70)

    # Test in local mode
    db = QdrantVectorDB(
        collection_name="test_collection",
        local_mode=True  # Use in-memory for testing
    )

    # Add test documents
    print("\nAdding test documents...")
    docs = [
        "Black Girls CODE teaches coding to young Black girls",
        "Outdoor Afro connects Black people to nature",
        "Techqueria supports Latinx in tech"
    ]
    metadata = [
        {"type": "Tech", "name": "Black Girls CODE"},
        {"type": "Outdoor", "name": "Outdoor Afro"},
        {"type": "Tech", "name": "Techqueria"}
    ]
    ids = ["doc1", "doc2", "doc3"]

    db.add(docs, metadata, ids)
    print(f"Total documents: {db.count()}")

    # Test search
    print("\nSearching for 'tech community'...")
    results = db.search("tech community", n_results=2)
    for i, doc in enumerate(results['documents'][0]):
        print(f"{i+1}. {doc[:60]}...")
        print(f"   Metadata: {results['metadatas'][0][i]}")

    print("\n" + "="*70)
    print("✅ QDRANT TEST COMPLETE")
    print("="*70)
