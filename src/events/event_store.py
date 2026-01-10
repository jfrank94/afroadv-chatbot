"""
Event storage using Qdrant for semantic search of events.

Stores events in a separate collection from platforms for flexible querying.

Updated: Now uses Qdrant for stability (no corruption issues)
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from src.infrastructure.vectordb import QdrantVectorDB

logger = logging.getLogger(__name__)


class EventStore:
    """
    Manages event storage and retrieval in Qdrant.

    Events are stored in a separate collection from platforms to enable:
    - Semantic search across events ("upcoming Black tech conferences")
    - Filtering by date, location, type
    - Different refresh cycles from platform data
    """

    def __init__(
        self,
        collection_name: str = "events",
        vector_db: Optional[QdrantVectorDB] = None,
        local_mode: bool = True
    ) -> None:
        """
        Initialize EventStore with Qdrant.

        Args:
            collection_name: Name of events collection
            vector_db: Optional existing QdrantVectorDB instance (avoids multiple instances)
            local_mode: If True, uses in-memory Qdrant (recommended for dev)
        """
        self.collection_name: str = collection_name

        # Use provided vector DB or create new one
        self.vector_db: QdrantVectorDB
        if vector_db is not None:
            # Share the client but use a different collection
            self.vector_db = vector_db

            # Update collection_name and ensure collection exists
            self.vector_db.collection_name = collection_name
            self.vector_db._setup_collection()  # Create events collection if needed

            logger.info(f"✓ EventStore using shared Qdrant client with collection '{collection_name}'")
        else:
            # Check config for cloud mode override
            import config
            use_cloud = getattr(config, 'USE_QDRANT_CLOUD', False)
            if use_cloud:
                local_mode = False
                logger.info("Using Qdrant Cloud for events (config.USE_QDRANT_CLOUD=true)")

            # Initialize Qdrant vector database
            self.vector_db = QdrantVectorDB(
                collection_name=collection_name,
                local_mode=local_mode
            )
            logger.info(f"✓ EventStore created new Qdrant client (local_mode={local_mode})")

        logger.info(f"✓ EventStore initialized with collection '{collection_name}'")

    def add_events(self, events: List[Dict[str, Any]], platform_id: str) -> int:
        """
        Add events to the collection.

        Args:
            events: List of event dictionaries
            platform_id: ID of the platform these events belong to

        Returns:
            Number of events added
        """
        if not events:
            logger.debug(f"No events to add for platform {platform_id}")
            return 0

        documents = []
        metadatas = []
        ids = []

        for i, event in enumerate(events):
            # Create searchable text from event
            document = self._create_event_document(event)

            # Generate unique ID
            event_id = f"{platform_id}_event_{datetime.now().strftime('%Y%m%d')}_{i}"

            # Metadata for filtering
            metadata = {
                'platform_id': platform_id,
                'org_name': event.get('org_name', ''),
                'event_type': event.get('event_type', 'other'),
                'source': event.get('source', 'unknown'),
                'url': event.get('url', ''),
                'published_date': event.get('published_date', ''),
                'last_updated': datetime.now().isoformat(),
                'title': event.get('title', '')[:200]  # ChromaDB metadata limit
            }

            # Add date if available
            if event.get('date'):
                metadata['date'] = event['date']

            # Add location if available
            if event.get('location'):
                metadata['location'] = event.get('location', '')[:200]

            documents.append(document)
            metadatas.append(metadata)
            ids.append(event_id)

        try:
            # Add to Qdrant collection
            success = self.vector_db.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )

            if success:
                logger.info(f"Added {len(events)} event(s) for platform {platform_id}")
                return len(events)
            else:
                logger.error(f"Failed to add events to Qdrant")
                return 0

        except Exception as e:
            logger.error(f"Error adding events to collection: {e}")
            return 0

    def search_events(
        self,
        query: str,
        platform_id: Optional[str] = None,
        event_type: Optional[str] = None,
        n_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search events by semantic similarity.

        Args:
            query: Search query
            platform_id: Filter by specific platform (optional)
            event_type: Filter by event type (optional)
            n_results: Number of results to return

        Returns:
            List of event dictionaries with metadata
        """
        try:
            # Build metadata filter
            filter_dict = {}
            if platform_id:
                filter_dict['platform_id'] = platform_id
            if event_type:
                filter_dict['event_type'] = event_type

            # Search Qdrant collection
            results = self.vector_db.search(
                query=query,
                n_results=n_results,
                filter_dict=filter_dict if filter_dict else None
            )

            # Format results and filter for future events only
            events = []
            today = datetime.now().date()

            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    metadata = results['metadatas'][0][i] if results['metadatas'] else {}

                    # Parse event date
                    date_str = metadata.get('date')
                    event_date = None
                    if date_str:
                        try:
                            event_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                        except ValueError:
                            pass  # Keep event if date can't be parsed

                    # Only include future events (today or later)
                    if event_date is None or event_date >= today:
                        events.append({
                            'title': metadata.get('title', 'Untitled Event'),
                            'description': doc,
                            'url': metadata.get('url', ''),
                            'event_type': metadata.get('event_type', 'other'),
                            'date': metadata.get('date'),
                            'location': metadata.get('location'),
                            'org_name': metadata.get('org_name', ''),
                            'platform_id': metadata.get('platform_id', ''),
                            'source': metadata.get('source', 'unknown'),
                            'distance': results['distances'][0][i] if results['distances'] else None
                        })

            logger.info(f"Found {len(events)} future event(s) for query: {query}")
            return events

        except Exception as e:
            logger.error(f"Error searching events: {e}")
            return []

    def get_platform_events(self, platform_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get future events for a specific platform.

        Args:
            platform_id: Platform ID
            limit: Maximum number of events to return

        Returns:
            List of future event dictionaries
        """
        try:
            # Get all documents from Qdrant (no direct "get by filter" in our wrapper)
            # So we'll search with a broad query and filter
            results = self.vector_db.search(
                query=platform_id,  # Use platform_id as query
                n_results=limit * 2,  # Get extra to account for past events we'll filter out
                filter_dict={'platform_id': platform_id}
            )

            events = []
            today = datetime.now().date()

            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    metadata = results['metadatas'][0][i] if results['metadatas'] else {}

                    # Parse event date
                    date_str = metadata.get('date')
                    event_date = None
                    if date_str:
                        try:
                            event_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                        except ValueError:
                            pass  # Keep event if date can't be parsed

                    # Only include future events (today or later)
                    if event_date is None or event_date >= today:
                        events.append({
                            'title': metadata.get('title', 'Untitled Event'),
                            'description': doc,
                            'url': metadata.get('url', ''),
                            'event_type': metadata.get('event_type', 'other'),
                            'date': metadata.get('date'),
                            'location': metadata.get('location'),
                            'org_name': metadata.get('org_name', ''),
                            'platform_id': platform_id,
                            'source': metadata.get('source', 'unknown')
                        })

                        # Stop if we've collected enough future events
                        if len(events) >= limit:
                            break

            logger.info(f"Retrieved {len(events)} future event(s) for platform {platform_id}")
            return events

        except Exception as e:
            logger.error(f"Error getting platform events: {e}")
            return []

    def clear_platform_events(self, platform_id: str) -> bool:
        """
        Remove all events for a specific platform using Qdrant's filter-based deletion.
        Useful for refresh/update operations.

        Args:
            platform_id: Platform ID

        Returns:
            True if successful, False otherwise
        """
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            # Use Qdrant's native filter-based deletion (much more efficient)
            # No need to fetch all events first
            self.vector_db.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="platform_id",
                            match=MatchValue(value=platform_id)
                        )
                    ]
                )
            )
            logger.info(f"Cleared all events for platform {platform_id} using filter-based deletion")
            return True

        except Exception as e:
            logger.error(f"Error clearing platform events: {e}", exc_info=True)
            return False

    def get_collection_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the events collection.

        Returns:
            Dictionary with collection stats
        """
        try:
            # Get total count
            count = self.vector_db.count()

            # Get sample of events to analyze
            sample = self.vector_db.get()

            # Count by source
            sources: Dict[str, int] = {}
            event_types: Dict[str, int] = {}

            if sample['metadatas']:
                for metadata in sample['metadatas']:
                    source = metadata.get('source', 'unknown')
                    sources[source] = sources.get(source, 0) + 1

                    event_type = metadata.get('event_type', 'other')
                    event_types[event_type] = event_types.get(event_type, 0) + 1

            return {
                'total_events': count,
                'sources': sources,
                'event_types': event_types
            }

        except Exception as e:
            logger.error(f"Error getting collection stats: {e}")
            return {'total_events': 0, 'sources': {}, 'event_types': {}}

    def _create_event_document(self, event: Dict[str, Any]) -> str:
        """
        Create searchable document text from event.

        Args:
            event: Event dictionary

        Returns:
            Formatted document text for embedding
        """
        title = event.get('title', 'Untitled Event')
        description = event.get('description', '')
        event_type = event.get('event_type', 'other')
        org_name = event.get('org_name', '')
        location = event.get('location', '')
        date = event.get('date', '')

        # Combine fields into searchable text
        parts = [f"{title}"]

        if event_type:
            parts.append(f"Type: {event_type}")

        if org_name:
            parts.append(f"Organized by: {org_name}")

        if date:
            parts.append(f"Date: {date}")

        if location:
            parts.append(f"Location: {location}")

        if description:
            parts.append(f"Description: {description[:300]}")  # Truncate long descriptions

        return " | ".join(parts)


if __name__ == '__main__':
    # Quick test
    logging.basicConfig(level=logging.INFO)

    # Initialize store
    store = EventStore()

    # Add test event
    test_events = [{
        'title': 'AfroTech Conference 2025',
        'description': 'Annual conference for Black professionals in tech',
        'url': 'https://afrotech.com/conference',
        'event_type': 'conference',
        'date': '2025-11-08',
        'location': 'Houston, TX',
        'org_name': 'AfroTech',
        'org_id': 'tech_afrotech_005',
        'source': 'rss'
    }]

    store.add_events(test_events, 'tech_afrotech_005')

    # Search for events
    results = store.search_events('tech conferences', n_results=3)

    print(f"\nFound {len(results)} events:")
    for event in results:
        print(f"\n- {event['title']}")
        print(f"  Type: {event['event_type']}")
        print(f"  Org: {event['org_name']}")

    # Get stats
    stats = store.get_collection_stats()
    print(f"\nCollection stats: {stats}")
