#!/usr/bin/env python3
"""
Build vector database index from platform data.

Usage:
    python scripts/build_index.py [--cloud]

Simple rebuild approach for <500 platforms:
- Loads data from data/platforms.json
- Generates embeddings for all platforms
- Rebuilds entire Qdrant index (<30 seconds)
- No incremental sync needed

Updated: Now uses Qdrant for stability (no corruption issues)
"""

import json
import sys
from pathlib import Path
import logging
import argparse

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from src.infrastructure.embeddings import prepare_platform_text
from src.infrastructure.vectordb import QdrantVectorDB
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_platforms(data_path: str = "data/platforms.json") -> list:
    """
    Load platform data from JSON file.

    Args:
        data_path: Path to platforms.json

    Returns:
        List of platform dictionaries
    """
    path = project_root / data_path
    logger.info(f"Loading platforms from {path}")

    if not path.exists():
        logger.error(f"Data file not found: {path}")
        logger.info("Please create data/platforms.json first")
        logger.info("You can export from Excel or start with sample data")
        return []

    with open(path, "r", encoding="utf-8") as f:
        platforms = json.load(f)

    logger.info(f"Loaded {len(platforms)} platforms")
    return platforms


def build_index(local_mode: bool = True):
    """
    Build vector database index using Qdrant.

    Args:
        local_mode: If True, use in-memory Qdrant. If False, use Qdrant Cloud.
    """
    logger.info("=" * 60)
    logger.info("Building Vector Database Index (Qdrant)")
    logger.info("=" * 60)

    # Load data
    platforms = load_platforms()
    if not platforms:
        logger.error("No platforms found. Aborting.")
        return

    # Validate required fields
    required_fields = ["id", "name", "type"]
    for i, platform in enumerate(platforms):
        missing = [f for f in required_fields if f not in platform]
        if missing:
            logger.error(f"Platform {i} missing required fields: {missing}")
            logger.error(f"Platform data: {platform}")
            return

    # Prepare texts for embedding
    logger.info("\n" + "=" * 60)
    logger.info("Step 1: Preparing Platform Texts")
    logger.info("=" * 60)
    texts = [prepare_platform_text(p) for p in platforms]

    logger.info(f"\nSample prepared text (first platform):")
    logger.info(f"{'-' * 60}")
    logger.info(texts[0][:300] + "..." if len(texts[0]) > 300 else texts[0])
    logger.info(f"{'-' * 60}")

    # Initialize Qdrant vector database (handles embeddings internally)
    logger.info("\n" + "=" * 60)
    logger.info(f"Step 2: Initializing Qdrant (local_mode={local_mode})")
    logger.info("=" * 60)

    db = QdrantVectorDB(
        collection_name="poc_platforms",
        local_mode=local_mode
    )

    # Clear existing data if rebuilding
    logger.info("Clearing existing data...")
    db.clear()

    # Prepare metadata
    logger.info("\n" + "=" * 60)
    logger.info("Step 3: Adding Platforms to Qdrant")
    logger.info("=" * 60)

    ids = [p["id"] for p in platforms]
    metadatas = [
        {
            "name": p["name"],
            "type": p["type"],
            "category": p.get("category", ""),
            "focus_area": p.get("focus_area", ""),
            "website": p.get("website", ""),
            "founded": p.get("founded", ""),
            "community_size": p.get("community_size", ""),
            "geographic_focus": p.get("geographic_focus", "")
        }
        for p in platforms
    ]

    # Add to database (Qdrant generates embeddings internally)
    success = db.add(
        documents=texts,
        metadatas=metadatas,
        ids=ids
    )

    if not success:
        logger.error("Failed to add platforms to Qdrant")
        return

    # Display stats
    logger.info("\n" + "=" * 60)
    logger.info("Index Build Complete!")
    logger.info("=" * 60)
    logger.info(f"Collection: poc_platforms")
    logger.info(f"Total platforms: {db.count()}")
    logger.info(f"Database: Qdrant ({'local in-memory' if local_mode else 'cloud'})")

    # Type breakdown
    type_counts = {}
    for p in platforms:
        ptype = p.get("type", "Unknown")
        type_counts[ptype] = type_counts.get(ptype, 0) + 1

    logger.info("\nPlatforms by type:")
    for ptype, count in sorted(type_counts.items()):
        logger.info(f"  {ptype}: {count}")

    logger.info("\n" + "=" * 60)
    logger.info("Next steps:")
    logger.info("  1. Run: python scripts/test_queries.py")
    logger.info("  2. Test retrieval quality with sample queries")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build vector database index with Qdrant")
    parser.add_argument(
        "--cloud",
        action="store_true",
        help="Use Qdrant Cloud instead of local mode (requires QDRANT_URL and QDRANT_API_KEY in .env)"
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Force local mode (overrides USE_QDRANT_CLOUD environment variable)"
    )

    args = parser.parse_args()

    # Determine mode: CLI flag > environment variable > default (local)
    if args.local:
        local_mode = True
        logger.info("Using local mode (--local flag)")
    elif args.cloud:
        local_mode = False
        logger.info("Using cloud mode (--cloud flag)")
    else:
        # Check environment variable
        local_mode = not config.USE_QDRANT_CLOUD
        if config.USE_QDRANT_CLOUD:
            logger.info("Using Qdrant Cloud (USE_QDRANT_CLOUD=true in .env)")
        else:
            logger.info("Using local mode (USE_QDRANT_CLOUD=false or not set)")

    build_index(local_mode=local_mode)
