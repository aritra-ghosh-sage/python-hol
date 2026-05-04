"""Configuration management endpoints.

Routes:
    GET /config  -- Return the current retriever configuration.
    PUT /config  -- Update one or more configuration fields.
"""

import logging

import api  # shared state — accessed inside function bodies to avoid circular-import issues
from api_models import ConfigResponse, ConfigUpdateRequest
from fastapi import APIRouter, HTTPException
from hybrid_rag import (
    HybridRetriever,
    KNOWLEDGE_DB_DIRECTORY,
    get_sample_documents,
    initialize_vector_db,
    is_valid_collection_name,
    list_existing_collections,
    open_collection,
    save_config_to_disk,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _config_to_response(cfg: object) -> ConfigResponse:
    """Convert a HybridRetrieverConfig into a ConfigResponse.

    Args:
        cfg: A HybridRetrieverConfig instance.

    Returns:
        A ConfigResponse populated from ``cfg``.
    """
    return ConfigResponse(
        semantic_top_k=cfg.semantic_top_k,
        keyword_top_k=cfg.keyword_top_k,
        final_top_k=cfg.final_top_k,
        semantic_weight=cfg.semantic_weight,
        keyword_weight=cfg.keyword_weight,
        enable_rerank=cfg.enable_rerank,
        pre_rerank_top_k=cfg.pre_rerank_top_k,
        collection_name=cfg.collection_name,
    )


@router.get(
    "/config",
    response_model=ConfigResponse,
    tags=["Configuration"],
    summary="Get retriever configuration",
)
async def get_config() -> ConfigResponse:
    """Get the current retriever configuration.

    Returns:
        ConfigResponse with all configuration parameters.

    Raises:
        HTTPException: 503 if retriever not initialized.

    Example:
        GET /config
        Response: {"semantic_top_k": 10, "keyword_top_k": 10, ...}
    """
    if api._config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever not initialized. Try again later.",
        )
    return _config_to_response(api._config)


@router.put(
    "/config",
    response_model=ConfigResponse,
    tags=["Configuration"],
    summary="Update retriever configuration",
)
async def update_config(request: ConfigUpdateRequest) -> ConfigResponse:
    """Update the retriever configuration with new values.

    Only provided fields are updated. Configuration updates are validated
    before being applied, ensuring semantic_weight + keyword_weight = 1.0
    and all parameters are within valid ranges.

    Args:
        request: ConfigUpdateRequest with fields to update (all optional).

    Returns:
        ConfigResponse with the updated configuration.

    Raises:
        HTTPException: 400 if validation fails, 503 if not initialized.

    Example:
        PUT /config
        {"semantic_weight": 0.8, "keyword_weight": 0.2}
        Response: {"semantic_top_k": 10, "semantic_weight": 0.8, ...}
    """
    if api._config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever not initialized. Try again later.",
        )

    try:
        update_dict = request.model_dump(exclude_unset=True)

        if not update_dict:
            logger.debug("No configuration updates provided")
            return _config_to_response(api._config)

        logger.info("Updating configuration with: %s", update_dict)

        new_collection_name = update_dict.get("collection_name")
        collection_changed = (
            new_collection_name is not None
            and new_collection_name != api._config.collection_name
        )
        if new_collection_name is not None and not is_valid_collection_name(
            new_collection_name
        ):
            raise ValueError(
                f"Invalid collection name '{new_collection_name}': must be 6-20 chars, "
                "alphanumeric/underscore/hyphen only"
            )

        api._config = api._config.update(**update_dict)

        if collection_changed:
            logger.info(
                "Collection name changed to '%s', re-initializing vector DB",
                api._config.collection_name,
            )
            existing = list_existing_collections(KNOWLEDGE_DB_DIRECTORY)
            if api._config.collection_name in existing:
                new_collection = open_collection(
                    persist_dir=KNOWLEDGE_DB_DIRECTORY,
                    collection_name=api._config.collection_name,
                )
                logger.info(
                    "Switched to existing collection '%s'", api._config.collection_name
                )
            else:
                documents = get_sample_documents()
                new_collection = initialize_vector_db(
                    documents,
                    persist_dir=KNOWLEDGE_DB_DIRECTORY,
                    collection_name=api._config.collection_name,
                )
                logger.info(
                    "Created new collection '%s' with sample documents",
                    api._config.collection_name,
                )
            api._retriever = HybridRetriever(new_collection, api._config)
            logger.info(
                "Retriever re-initialized with collection '%s'",
                api._config.collection_name,
            )

        prev_version = api._corpus_version
        api._cache_generation += 1
        api._corpus_version = api._build_corpus_version_token()
        logger.info(
            "cache.invalidation event=config_change prev_version=%s new_version=%s",
            prev_version,
            api._corpus_version,
        )
        if api._cache is not None:
            try:
                api.lazy_cache.clear()
                logger.info("Config updated; cache cleared")
            except Exception as exc:
                logger.warning("Failed to clear cache after config update: %s", exc)
        else:
            logger.debug("Config updated; cache not initialized")

        try:
            save_config_to_disk(api._config, KNOWLEDGE_DB_DIRECTORY)
            logger.info("Configuration persisted to disk")
        except Exception as exc:
            logger.error("Failed to persist configuration to disk: %s", exc)
            raise HTTPException(
                status_code=500,
                detail=(
                    "Configuration updated in memory but could not be persisted to disk. "
                    "Settings will revert on restart."
                ),
            )

        logger.info("Configuration updated successfully")
        return _config_to_response(api._config)

    except ValueError as exc:
        logger.warning("Configuration validation failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=f"Configuration validation failed: {str(exc)}",
        )
    except TypeError as exc:
        logger.warning("Invalid configuration parameter: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid configuration parameter: {str(exc)}",
        )
    except Exception as exc:
        logger.error("Configuration update failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Configuration update failed: {str(exc)}",
        )
