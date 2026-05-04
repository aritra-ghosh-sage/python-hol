"""Configuration persistence utilities for hybrid RAG."""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from .config import HybridRetrieverConfig
from .constants import KNOWLEDGE_DB_DIRECTORY

logger = logging.getLogger(__name__)

__all__ = [
    "save_config_to_disk",
    "load_config_from_disk",
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
