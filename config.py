"""
Configuration settings for PoC Platforms RAG Chatbot.

Loads environment variables and provides centralized config access.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file (if it exists)
load_dotenv()

# Helper function to get environment variables (supports both .env and Streamlit secrets)
def get_env(key: str, default: str = None) -> str:
    """Get environment variable, checking Streamlit secrets first, then .env"""
    value = None

    # Try Streamlit secrets first (for cloud deployment)
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and key in st.secrets:
            value = st.secrets[key]
            # Only use if not None or empty
            if value is not None and str(value).strip() != "":
                return str(value)
    except (ImportError, FileNotFoundError, KeyError):
        pass

    # Fall back to os.getenv (for local development)
    value = os.getenv(key)
    if value is not None and value != "":
        return value

    # Return default if nothing found
    return default if default is not None else ""

# Project paths
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
VECTOR_DB_PATH = PROJECT_ROOT / "qdrant_storage"  # Qdrant local storage

# Data files
PLATFORMS_JSON = DATA_DIR / "platforms.json"
PLATFORMS_EXCEL = PROJECT_ROOT / "poc_platforms_database.xlsx"

# LLM API Keys (with fallback chain)
CEREBRAS_API_KEY = get_env("CEREBRAS_API_KEY")
DEEPSEEK_API_KEY = get_env("DEEPSEEK_API_KEY")
ANTHROPIC_API_KEY = get_env("ANTHROPIC_API_KEY")
TAVILY_API_KEY = get_env("TAVILY_API_KEY")  # For event discovery

# Qdrant Cloud Configuration (for production deployment)
QDRANT_URL = get_env("QDRANT_URL")  # e.g., https://xyz-example.eu-central.aws.cloud.qdrant.io:6333
QDRANT_API_KEY = get_env("QDRANT_API_KEY")
USE_QDRANT_CLOUD = get_env("USE_QDRANT_CLOUD", "false").lower() == "true"

# LLM Configuration
CEREBRAS_MODEL = "llama3.1-70b"
DEEPSEEK_MODEL = "deepseek-chat"
CLAUDE_MODEL = "claude-3-5-haiku-20241022"

# Embedding Model Configuration
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384

# Vector DB Configuration
COLLECTION_NAME = "poc_platforms"
SIMILARITY_METRIC = "cosine"

# Retrieval Configuration
DEFAULT_TOP_K = 5
MIN_SIMILARITY_THRESHOLD = 0.3  # Include loosely related results

# Generation Configuration
MAX_TOKENS = 1000
TEMPERATURE = 0.7
CONVERSATION_MEMORY_TURNS = 5  # Last N turns to remember

# LLM-specific Token Limits
class LLMTokenLimits:
    """Token limits for different LLM operations."""
    URL_FINDER_MAX_TOKENS = 300
    EVENT_PAGE_FINDER_MAX_TOKENS = 400
    EVENT_EXTRACTOR_MAX_TOKENS = 2500
    DEFAULT_MAX_TOKENS = 1024

# Content Processing Limits
class ContentLimits:
    """Limits for processing web content."""
    MAX_CONTENT_LENGTH = 8000  # characters
    MAX_LINKS_TO_PROCESS = 30
    MAX_EVENTS_PER_PAGE = 50

# Event Configuration
class EventConfig:
    """Event-related configuration."""
    EVENT_EXPIRY_MONTHS = 12
    MAX_EVENTS_PER_PLATFORM = 100
    COLLECTION_NAME = "events"

# Vector Database Collections
class VectorDBCollections:
    """Collection names for different vector databases."""
    PLATFORMS_COLLECTION = "poc_platforms"
    EVENTS_COLLECTION = "events"

# Streamlit Configuration
APP_TITLE = "PoC Platforms Finder"
APP_ICON = "🌍"
PAGE_CONFIG = {
    "page_title": APP_TITLE,
    "page_icon": APP_ICON,
    "layout": "centered",
    "initial_sidebar_state": "collapsed"
}

# Validation: Check if at least one LLM API key is configured
def validate_config():
    """Validate that required configuration is present."""
    errors = []

    # Check for at least one LLM API key
    if not any([CEREBRAS_API_KEY, DEEPSEEK_API_KEY, ANTHROPIC_API_KEY]):
        errors.append(
            "No LLM API keys found! Set at least one of: "
            "CEREBRAS_API_KEY, DEEPSEEK_API_KEY, or ANTHROPIC_API_KEY"
        )

    # Check data file exists
    if not PLATFORMS_JSON.exists() and not PLATFORMS_EXCEL.exists():
        errors.append(
            f"No platform data found! Expected {PLATFORMS_JSON} or {PLATFORMS_EXCEL}"
        )

    return errors

# Print configuration status on import (for debugging)
if __name__ == "__main__":
    print("🔧 Configuration Status:")
    print(f"  Project Root: {PROJECT_ROOT}")
    print(f"  Data Directory: {DATA_DIR}")
    print(f"  Vector DB Path: {VECTOR_DB_PATH}")
    print(f"\n🔑 API Keys Configured:")
    print(f"  Cerebras: {'✅' if CEREBRAS_API_KEY else '❌'}")
    print(f"  DeepSeek: {'✅' if DEEPSEEK_API_KEY else '❌'}")
    print(f"  Claude Haiku: {'✅' if ANTHROPIC_API_KEY else '❌'}")

    errors = validate_config()
    if errors:
        print(f"\n⚠️  Configuration Errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print(f"\n✅ Configuration valid!")
