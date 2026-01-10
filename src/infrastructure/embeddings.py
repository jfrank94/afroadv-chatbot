"""
Embedding model wrapper for RAG pipeline.

Uses sentence-transformers/all-MiniLM-L6-v2:
- Free, local, 384 dimensions, ~90MB
- 5x faster than alternatives
- Perfect for <500 platforms
"""

from sentence_transformers import SentenceTransformer
from typing import List
import logging
from src.infrastructure.embedding_singleton import get_embedding_model

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Wrapper for sentence-transformers embedding model."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Initialize embedding model using singleton pattern for memory efficiency.

        Uses shared model instance across all EmbeddingModel instances to prevent
        loading the same ~90MB model multiple times in memory.

        Args:
            model_name: HuggingFace model name (default: all-MiniLM-L6-v2)
        """
        logger.info(f"Getting embedding model (singleton): {model_name}")
        self.model = get_embedding_model(model_name)
        self.dimension = self.model.get_sentence_embedding_dimension()
        logger.debug(f"Model dimension: {self.dimension}")

    def embed_text(self, text: str) -> List[float]:
        """
        Embed a single text string.

        Args:
            text: Text to embed

        Returns:
            List of floats (embedding vector)
        """
        return self.model.encode(text, convert_to_tensor=False).tolist()

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """
        Embed multiple texts efficiently.

        Args:
            texts: List of texts to embed
            batch_size: Batch size for processing

        Returns:
            List of embedding vectors
        """
        logger.info(f"Embedding {len(texts)} texts in batches of {batch_size}")
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_tensor=False
        )
        return embeddings.tolist()


def prepare_platform_text(platform: dict) -> str:
    """
    Prepare platform record for embedding with 2025 optimization strategy.

    Uses keyword repetition to boost semantic relevance:
    - Name appears 2x (title + body)
    - Focus area emphasized
    - Tags repeated for better matching

    Args:
        platform: Platform dictionary from data/platforms.json

    Returns:
        Rich text representation optimized for semantic search
    """
    parts = [
        # Name twice for emphasis
        platform.get("name", ""),

        # Type and focus area
        f"Type: {platform.get('type', '')}",
        f"Focus: {platform.get('focus_area', '')}",

        # Description (main content)
        platform.get("description", ""),

        # Key details
        f"Programs: {platform.get('key_programs', '')}",
        f"Location: {platform.get('geographic_focus', '')}",

        # Name again for semantic boost
        f"Community: {platform.get('name', '')}",

        # Tags repeated for better keyword matching
        " ".join(platform.get("tags", [])),
        " ".join(platform.get("tags", []))  # Repeat tags
    ]

    # Join and clean
    text = " | ".join(filter(None, parts))
    return text.strip()


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    model = EmbeddingModel()

    test_platform = {
        "name": "Outdoor Afro",
        "type": "Outdoor/Travel",
        "focus_area": "Black Outdoor Recreation",
        "description": "National nonprofit connecting Black people to nature",
        "key_programs": "Leadership training, local outings, national events",
        "geographic_focus": "United States",
        "tags": ["black", "outdoors", "hiking", "nature"]
    }

    text = prepare_platform_text(test_platform)
    print(f"\nPrepared text:\n{text}\n")

    embedding = model.embed_text(text)
    print(f"Embedding dimension: {len(embedding)}")
    print(f"First 5 values: {embedding[:5]}")
