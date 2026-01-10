"""RAG retrieval logic for semantic search.

This module implements the retrieval component of a RAG (Retrieval-Augmented
Generation) pipeline using Qdrant vector database for stable, scalable semantic
search over platform documents.

Key features:
- Semantic search using pre-computed embeddings
- Type-based filtering (Tech, Outdoor/Travel)
- Relevance scoring with cosine similarity
- Result formatting for downstream LLM generation
"""

from typing import List, Dict, Optional, Any
import logging
from src.infrastructure.vectordb import QdrantVectorDB

logger = logging.getLogger(__name__)


class Retriever:
    """Handles semantic search and retrieval for RAG pipeline.

    Encapsulates the retrieval logic using Qdrant vector database for
    finding relevant platforms based on semantic similarity to user queries.
    Supports filtering by platform type (Tech, Outdoor/Travel).

    Attributes:
        vector_db: QdrantVectorDB instance managing the vector store
    """

    def __init__(
        self,
        vector_db: Optional[QdrantVectorDB] = None,
        collection_name: str = "poc_platforms",
        local_mode: bool = True
    ) -> None:
        """
        Initialize retriever with Qdrant vector database.

        Creates or connects to a Qdrant collection. If no vector_db is provided,
        creates a new QdrantVectorDB instance.

        Args:
            vector_db: Existing QdrantVectorDB instance. If None, creates new instance.
            collection_name: Name of the Qdrant collection (default: "poc_platforms")
            local_mode: If True, uses local persistent Qdrant for development.
                       If False, uses cloud Qdrant (requires QDRANT_URL and QDRANT_API_KEY)
                       Default is True, but overridden by config.USE_QDRANT_CLOUD if set
        """
        # Check config for cloud mode override
        import config
        use_cloud = getattr(config, 'USE_QDRANT_CLOUD', False)
        if use_cloud:
            local_mode = False
            logger.info("Using Qdrant Cloud (config.USE_QDRANT_CLOUD=true)")

        self.vector_db = vector_db or QdrantVectorDB(
            collection_name=collection_name,
            local_mode=local_mode
        )

        logger.info("Retriever initialized with Qdrant")

    def retrieve(
        self,
        query: str,
        n_results: int = 5,
        type_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve top-k relevant platforms for a query.

        Performs semantic search by embedding the query and finding the most similar
        platforms in the vector database. Results are sorted by relevance score
        (distance from query embedding).

        Args:
            query: Natural language query (e.g., "Black women in tech", "hiking groups")
            n_results: Number of results to return (default: 5)
            type_filter: Optional platform type filter:
                        - "Tech" for technology platforms
                        - "Outdoor/Travel" for outdoor/travel platforms
                        If None, returns results from all types

        Returns:
            List of platform dictionaries, each containing:
                - id: Platform unique identifier
                - name: Platform name
                - type: Platform type (Tech or Outdoor/Travel)
                - category: Platform category (e.g., Nonprofit, Community)
                - focus_area: Primary focus of the platform
                - description: Full description text
                - website: Platform website URL
                - founded: Year founded (if available)
                - community_size: Size of community
                - key_programs: Description of key programs
                - geographic_focus: Geographic scope
                - tags: List of relevant tags
                - relevance_score: Cosine similarity score (0-1, higher = more relevant)

        Example:
            >>> retriever = Retriever(local_mode=True)
            >>> results = retriever.retrieve("Black women hiking", n_results=3, type_filter="Outdoor/Travel")
            >>> for platform in results:
            ...     print(f"{platform['name']}: {platform['relevance_score']:.3f}")
        """
        if not query.strip():
            logger.warning("Empty query received")
            return []

        logger.info(f"Retrieving platforms for query: '{query}'")

        # Build filter if specified
        filter_dict = None
        if type_filter:
            filter_dict = {"type": type_filter}

        # HYBRID SEARCH: Combine vector search with keyword matching
        # Always run keyword search as fallback for better brand name matching

        # Step 1: Vector search
        results = self.vector_db.search(
            query=query,
            n_results=n_results * 2,  # Get more for better coverage
            filter_dict=filter_dict
        )

        platforms = self._format_results(results)
        logger.info(f"Vector search: {len(platforms)} platforms")

        # Step 2: Always run keyword search as fallback (cheap operation)
        keyword_matches = self._keyword_search(query.lower(), filter_dict)
        logger.info(f"Keyword search: {len(keyword_matches)} name matches")

        # Merge keyword matches with vector results
        platform_ids_seen = {p['id'] for p in platforms}
        for keyword_match in keyword_matches:
            if keyword_match['id'] not in platform_ids_seen:
                keyword_match['relevance_score'] = 0.95  # High score for exact name match
                platforms.append(keyword_match)
                logger.info(f"Added keyword match: {keyword_match['name']}")

        # Step 3: Boost platforms with name matches in existing results
        query_lower = query.lower()
        # Extract just the potential brand name (ignore common question words)
        query_words = [w for w in query_lower.split() if w not in ['tell', 'me', 'about', 'more', 'what', 'is', 'find', 'show', 'the', 'a', 'an']]
        brand_query = ' '.join(query_words)

        for platform in platforms:
            name_lower = platform['name'].lower()
            # Check if brand name appears in platform name
            if brand_query and (brand_query in name_lower or name_lower in brand_query):
                old_score = platform.get('relevance_score', 0.5)
                platform['relevance_score'] = min(0.98, old_score + 0.4)  # Strong boost
                logger.info(f"Boosted '{platform['name']}': {old_score:.3f} → {platform['relevance_score']:.3f}")

        # Step 4: Re-sort and return top results
        platforms = sorted(platforms, key=lambda x: x.get('relevance_score', 0), reverse=True)[:n_results]

        logger.info(f"Final {len(platforms)} results (hybrid search)")
        return platforms

    def _keyword_search(self, query: str, filter_dict: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Keyword-based search through platform names for exact/partial matches.

        This is a fallback search method for brand name queries that may not
        work well with vector similarity (e.g., "Soul Trak", "Techqueria").

        Args:
            query: Lowercase query string
            filter_dict: Optional type filter

        Returns:
            List of matching platforms with metadata
        """
        import json
        import config

        matches = []

        # Load platforms from JSON
        try:
            with open(config.PLATFORMS_JSON, 'r') as f:
                all_platforms = json.load(f)

            # Extract meaningful words from query (ignore stopwords)
            stopwords = {'tell', 'me', 'about', 'more', 'what', 'is', 'are', 'the', 'a', 'an', 'find', 'show', 'looking', 'for'}
            query_words = [w for w in query.split() if w not in stopwords and len(w) > 2]

            # Search for name matches
            for platform in all_platforms:
                name_lower = platform.get('name', '').lower()

                # Check for matches:
                # 1. Exact substring match
                # 2. All query words appear in name
                is_match = False

                if query in name_lower or name_lower in query:
                    is_match = True
                elif query_words and all(word in name_lower for word in query_words):
                    is_match = True

                if is_match:
                    # Apply type filter if specified
                    if filter_dict and filter_dict.get('type'):
                        if platform.get('type') != filter_dict['type']:
                            continue

                    # Format as platform dict
                    matches.append({
                        "id": platform.get("id", ""),
                        "name": platform.get("name", ""),
                        "type": platform.get("type", ""),
                        "category": platform.get("category", ""),
                        "focus_area": platform.get("focus_area", ""),
                        "description": platform.get("description", ""),
                        "website": platform.get("website", ""),
                        "founded": platform.get("founded", ""),
                        "community_size": platform.get("community_size", ""),
                        "key_programs": platform.get("key_programs", ""),
                        "geographic_focus": platform.get("geographic_focus", ""),
                        "tags": platform.get("tags", []),
                        "relevance_score": 0.9  # High score for keyword match
                    })

        except Exception as e:
            logger.warning(f"Keyword search failed: {e}")

        return matches

    def _format_results(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Format Qdrant results into clean platform dictionaries.

        Converts the raw Qdrant response format (parallel lists) into a list
        of platform dictionaries with proper field mapping.

        Args:
            results: Raw results from Qdrant with keys 'ids', 'distances', 'metadatas'
                    in the format: {'ids': [[...]], 'distances': [[...]], ...}

        Returns:
            List of platform dictionaries with all fields properly extracted
        """
        platforms = []

        # Qdrant (via our wrapper) returns results as parallel lists (same format as ChromaDB)
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for platform_id, distance, metadata in zip(ids, distances, metadatas):
            platform = {
                "id": platform_id,
                "name": metadata.get("name", ""),
                "type": metadata.get("type", ""),
                "category": metadata.get("category", ""),
                "focus_area": metadata.get("focus_area", ""),
                "description": metadata.get("description", ""),
                "website": metadata.get("website", ""),
                "founded": metadata.get("founded", ""),
                "community_size": metadata.get("community_size", ""),
                "key_programs": metadata.get("key_programs", ""),
                "geographic_focus": metadata.get("geographic_focus", ""),
                "tags": metadata.get("tags", "").split(", ") if metadata.get("tags") else [],
                "relevance_score": float(distance)  # Lower distance = more similar
            }
            platforms.append(platform)

        return platforms

    def get_stats(self) -> Dict[str, Any]:
        """
        Get retriever statistics and configuration.

        Returns information about the vector database collection, useful for
        debugging and monitoring the RAG system.

        Returns:
            Dictionary with keys:
                - 'total_documents': Number of platforms in the collection
                - 'collection_name': Name of the Qdrant collection
                - 'embedding_dimension': Dimension of embedding vectors
                - 'database_type': Always "Qdrant" for this implementation
        """
        return {
            "total_documents": self.vector_db.count(),
            "collection_name": self.vector_db.collection_name,
            "embedding_dimension": self.vector_db.embedding_dim,
            "database_type": "Qdrant"
        }


def format_platform_for_display(platform: Dict[str, Any]) -> str:
    """
    Format a platform dictionary for human-readable display.

    Converts a platform dictionary into a nicely formatted string suitable
    for displaying in the UI. Includes all relevant information with proper
    section breaks.

    Args:
        platform: Platform dictionary from retriever.retrieve() with keys
                 'name', 'type', 'category', 'focus_area', 'description', etc.

    Returns:
        Formatted markdown-style string for human display

    Example:
        >>> platform = {
        ...     "name": "Outdoor Afro",
        ...     "type": "Outdoor/Travel",
        ...     "description": "Connects Black people to nature"
        ... }
        >>> print(format_platform_for_display(platform))
        **Outdoor Afro**
        Type: Outdoor/Travel | Category: ...
    """
    lines = [
        f"**{platform['name']}**",
        f"Type: {platform['type']} | Category: {platform['category']}",
        f"Focus: {platform['focus_area']}",
        f"\n{platform['description']}",
    ]

    if platform.get("website"):
        lines.append(f"\nWebsite: {platform['website']}")

    if platform.get("key_programs"):
        lines.append(f"Key Programs: {platform['key_programs']}")

    if platform.get("community_size"):
        lines.append(f"Community Size: {platform['community_size']}")

    if platform.get("geographic_focus"):
        lines.append(f"Location: {platform['geographic_focus']}")

    return "\n".join(lines)


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    retriever = Retriever(collection_name="test_collection", local_mode=True)

    # Test retrieval (will be empty until database is built)
    results = retriever.retrieve("Black hiking groups", n_results=3)

    print(f"\nFound {len(results)} results")
    print("\nRetriever stats:")
    print(retriever.get_stats())
