"""Singleton embedding model manager for memory optimization.

This module implements the singleton pattern for SentenceTransformer models
to prevent loading the same model multiple times in memory.

The all-MiniLM-L6-v2 model is ~90MB. Without singleton pattern:
- EventStore instance: +90MB
- Retriever instance: +90MB
- Total: 180MB+ for duplicate models

With singleton pattern:
- All instances share one model: 90MB total
- ~50% memory reduction for typical usage

Thread-safety: Uses thread-safe singleton implementation.
"""

from sentence_transformers import SentenceTransformer
from typing import Dict, Optional
import threading
import logging

logger = logging.getLogger(__name__)


class EmbeddingModelSingleton:
    """Thread-safe singleton manager for SentenceTransformer models.

    Ensures only one instance of each model is loaded in memory, even when
    multiple components (EventStore, Retriever, etc.) need embeddings.

    Usage:
        >>> model = EmbeddingModelSingleton.get_model()
        >>> embedding = model.encode("text to embed")
    """

    _instances: Dict[str, SentenceTransformer] = {}
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get_model(
        cls,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    ) -> SentenceTransformer:
        """Get or create singleton embedding model instance.

        Returns cached model if already loaded, otherwise loads and caches it.
        Thread-safe implementation prevents duplicate loading in concurrent scenarios.

        Args:
            model_name: HuggingFace model identifier
                       (default: "sentence-transformers/all-MiniLM-L6-v2")

        Returns:
            SentenceTransformer model instance (shared across all callers)

        Example:
            >>> # First call loads the model
            >>> model1 = EmbeddingModelSingleton.get_model()
            >>> # Second call returns cached model (no loading)
            >>> model2 = EmbeddingModelSingleton.get_model()
            >>> assert model1 is model2  # Same object in memory
        """
        # Fast path: return if already loaded (no lock needed)
        if model_name in cls._instances:
            logger.debug(f"Returning cached embedding model: {model_name}")
            return cls._instances[model_name]

        # Slow path: load model with lock (thread-safe)
        with cls._lock:
            # Double-check pattern: another thread might have loaded it
            if model_name in cls._instances:
                logger.debug(f"Returning cached embedding model: {model_name}")
                return cls._instances[model_name]

            logger.info(f"Loading new embedding model: {model_name}")
            model = SentenceTransformer(model_name)
            cls._instances[model_name] = model
            logger.info(
                f"Embedding model loaded (dimension: "
                f"{model.get_sentence_embedding_dimension()})"
            )
            return model

    @classmethod
    def clear_cache(cls) -> None:
        """Clear all cached models (for testing/cleanup).

        Warning: Only call this if you're certain no code is using the models.
        Primarily useful for unit tests and memory cleanup scenarios.
        """
        with cls._lock:
            logger.info(f"Clearing {len(cls._instances)} cached embedding models")
            cls._instances.clear()

    @classmethod
    def get_cached_models(cls) -> list[str]:
        """Get list of currently cached model names.

        Returns:
            List of model names currently loaded in memory
        """
        return list(cls._instances.keys())


# Convenience function for common usage
def get_embedding_model(
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
) -> SentenceTransformer:
    """Get singleton embedding model instance.

    Convenience wrapper around EmbeddingModelSingleton.get_model().

    Args:
        model_name: HuggingFace model identifier

    Returns:
        Shared SentenceTransformer model instance

    Example:
        >>> from src.embedding_singleton import get_embedding_model
        >>> model = get_embedding_model()
        >>> embeddings = model.encode(["text1", "text2"])
    """
    return EmbeddingModelSingleton.get_model(model_name)


if __name__ == "__main__":
    # Demonstration of singleton behavior
    logging.basicConfig(level=logging.INFO)

    print("=== Singleton Pattern Demonstration ===\n")

    # First call: loads model
    print("1. First call (should load model):")
    model1 = get_embedding_model()
    print(f"   Model loaded: {model1}")
    print(f"   Memory address: {id(model1)}")

    # Second call: returns cached model
    print("\n2. Second call (should use cache):")
    model2 = get_embedding_model()
    print(f"   Model returned: {model2}")
    print(f"   Memory address: {id(model2)}")

    # Verify they're the same object
    print(f"\n3. Same object in memory? {model1 is model2}")

    # Test with different model
    print("\n4. Different model (should load new instance):")
    model3 = get_embedding_model("sentence-transformers/paraphrase-MiniLM-L3-v2")
    print(f"   Model loaded: {model3}")
    print(f"   Same as model1? {model1 is model3}")

    # Show cached models
    print(f"\n5. Currently cached models: {EmbeddingModelSingleton.get_cached_models()}")

    # Test embedding
    print("\n6. Test embedding:")
    text = "Black women in tech communities"
    embedding = model1.encode(text)
    print(f"   Text: {text}")
    print(f"   Embedding dimension: {len(embedding)}")
    print(f"   First 5 values: {embedding[:5]}")
