"""Configuration persistence utilities for hybrid RAG."""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from .config import DEFAULT_CONFIG, HybridRetrieverConfig
from .constants import COLLECTION_NAME_INVALID_MSG, KNOWLEDGE_DB_DIRECTORY
from .vectordb import is_valid_collection_name, list_existing_collections

logger = logging.getLogger(__name__)

__all__ = [
    "save_config_to_disk",
    "load_config_from_disk",
    "resolve_startup_config",
]


def get_config_file_path(persist_dir: str = KNOWLEDGE_DB_DIRECTORY) -> Path:
    """Get the path to the config file.

    Args:
        persist_dir: Directory where configuration is persisted.

    Returns:
        Path object pointing to config.json file.
    """
    return Path(persist_dir) / "config.json"


def save_config_to_disk(
    config: HybridRetrieverConfig, persist_dir: str = KNOWLEDGE_DB_DIRECTORY
) -> None:
    """Save configuration to disk as JSON.

    Creates the persist directory if it doesn't exist. Writes config atomically
    by writing to a temp file and renaming it.

    Args:
        config: Configuration instance to persist.
        persist_dir: Directory where configuration is persisted. Defaults to "./knowledge_db".

    Raises:
        OSError: If file operations fail.

    Example:
        >>> config = HybridRetrieverConfig(semantic_weight=0.8, keyword_weight=0.2)
        >>> save_config_to_disk(config)
    """
    config_path = get_config_file_path(persist_dir)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a unique temp file in the same directory so that the final
    # os.replace() is an atomic same-filesystem rename.  Using a unique name
    # per call means concurrent writers never clobber each other's temp file;
    # the last os.replace() wins, keeping the persisted JSON structurally valid.
    fd, tmp_name = tempfile.mkstemp(
        dir=config_path.parent, prefix="config.", suffix=".tmp"
    )
    temp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config.to_dict(), f, indent=2)
        # Atomic rename — guaranteed same filesystem because temp is in the
        # same directory as the target.
        temp_path.replace(config_path)
        logger.info(f"Configuration saved to {config_path}")
    except Exception as e:
        # Clean up temp file if it exists
        if temp_path.exists():
            temp_path.unlink()
        logger.error(f"Failed to save configuration: {e}")
        raise


def load_config_from_disk(
    persist_dir: str = KNOWLEDGE_DB_DIRECTORY,
) -> Optional[HybridRetrieverConfig]:
    """Load configuration from disk.

    Args:
        persist_dir: Directory where configuration is persisted. Defaults to "./knowledge_db".

    Returns:
        Loaded configuration instance, or None if file doesn't exist or is invalid.

    Example:
        >>> config = load_config_from_disk()
        >>> if config:
        ...     print(config.semantic_weight)
    """
    config_path = get_config_file_path(persist_dir)

    if not config_path.exists():
        logger.debug(f"No config file found at {config_path}")
        return None

    try:
        with open(config_path) as f:
            config_dict = json.load(f)
        config = HybridRetrieverConfig.from_dict(config_dict)
        logger.info(f"Configuration loaded from {config_path}")
        return config
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in config file {config_path}: {e}")
        return None
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid configuration in {config_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to load configuration from {config_path}: {e}")
        return None


def resolve_startup_config(
    persist_dir: str = KNOWLEDGE_DB_DIRECTORY,
) -> HybridRetrieverConfig:
    """Resolve startup configuration using the standard three-level precedence cascade.

    Hydration order (highest → lowest precedence):
      1. ``COLLECTION_NAME`` env var — if set, format-validated, and the named
         collection exists in ChromaDB, its value overrides ``collection_name``
         and is written back to config.json to keep both sources in sync.
      2. ``{persist_dir}/config.json`` — if it exists and its ``collection_name``
         exists in ChromaDB, it is used as the base config.
      3. ``DEFAULT_CONFIG`` — fallback when neither of the above applies.

    Args:
        persist_dir: Directory containing config.json and the ChromaDB store.

    Returns:
        Resolved HybridRetrieverConfig.

    Raises:
        ValueError: If ``COLLECTION_NAME`` env var has an invalid format.

    Example:
        >>> config = resolve_startup_config()
        >>> print(config.collection_name)
        rag_collection
    """
    from .vectordb import is_valid_collection_name, list_existing_collections

    env_collection_name = os.getenv("COLLECTION_NAME")
    if env_collection_name and not is_valid_collection_name(env_collection_name):
        raise ValueError(
            f"Invalid COLLECTION_NAME '{env_collection_name}': {COLLECTION_NAME_INVALID_MSG}"
        )

    existing = list_existing_collections(persist_dir)

    base_config = DEFAULT_CONFIG
    try:
        disk_config = load_config_from_disk(persist_dir)
        if disk_config is not None:
            if disk_config.collection_name in existing:
                base_config = disk_config
                logger.info(
                    "Loaded persisted configuration from disk (collection '%s' verified)",
                    disk_config.collection_name,
                )
            else:
                logger.warning(
                    "config.json collection_name '%s' not found in ChromaDB; using DEFAULT_CONFIG",
                    disk_config.collection_name,
                )
        else:
            logger.info("No persisted configuration found, using defaults")
    except Exception as e:
        logger.warning("Failed to load persisted configuration: %s; using defaults", e)

    if env_collection_name:
        if env_collection_name in existing:
            base_config = base_config.update(collection_name=env_collection_name)
            logger.info(
                "Overriding collection_name from COLLECTION_NAME env var: %s",
                env_collection_name,
            )
            try:
                save_config_to_disk(base_config, persist_dir)
                logger.info(
                    "Persisted env var collection_name '%s' to config.json",
                    env_collection_name,
                )
            except Exception as e:
                logger.warning("Failed to persist collection_name to config.json: %s", e)
        else:
            logger.warning(
                "COLLECTION_NAME env var '%s' not found in ChromaDB; ignoring",
                env_collection_name,
            )

    return base_config
