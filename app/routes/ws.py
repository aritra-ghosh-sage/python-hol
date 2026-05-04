"""WebSocket chat endpoint."""

import logging
import uuid
from typing import Literal

import api
from api import (
    WsErrorMessage,
    WsResultsMessage,
    WsStatusMessage,
    _shared_retrieve_documents,
    _to_filtered_document_results,
)
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from hybrid_rag import RetrievalError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time document queries.

    Client sends: {"query": str, "enable_rerank": bool?}
    Server sends (in sequence):
      - {"type": "status", "message": str}
      - {"type": "results", "query": str, "results": [...], "total_results": int}
      - {"type": "error", "message": str} (on failure)
    """
    await websocket.accept()
    logger.info("WebSocket client connected")

    try:
        while True:
            data = await websocket.receive_json()
            query = data.get("query", "").strip()
            enable_rerank = data.get("enable_rerank")

            if not query or len(query) < 1 or len(query) > 500:
                error_msg = WsErrorMessage(
                    message="Query must be between 1 and 500 characters"
                )
                await websocket.send_json(error_msg.model_dump())
                continue

            if api._retriever is None or api._config is None:
                error_msg = WsErrorMessage(message="Retriever not initialized")
                await websocket.send_json(error_msg.model_dump())
                continue

            try:
                status_msg = WsStatusMessage(message="Retrieving documents...")
                await websocket.send_json(status_msg.model_dump())

                ws_correlation_id = str(uuid.uuid4())
                ws_cache_status_out: list[str] = []
                results = _shared_retrieve_documents(
                    query,
                    enable_rerank=enable_rerank,
                    correlation_id=ws_correlation_id,
                    _out_cache_status=ws_cache_status_out,
                )
                doc_results = _to_filtered_document_results(
                    results, min_score_threshold=0.40
                )

                _raw_status = ws_cache_status_out[0] if ws_cache_status_out else "MISS"
                ws_cache_status: Literal["HIT", "MISS", "ERROR"] = (
                    _raw_status if _raw_status in ("HIT", "MISS", "ERROR") else "MISS"
                )

                results_msg = WsResultsMessage(
                    query=query,
                    results=doc_results,
                    total_results=len(doc_results),
                    cache_status=ws_cache_status,
                )
                await websocket.send_json(results_msg.model_dump())
                logger.info(
                    "WebSocket query succeeded: %s... (%d results after filtering)",
                    query[:50],
                    len(doc_results),
                )

            except RetrievalError as e:
                logger.error("WebSocket retrieval error: %s", e)
                error_msg = WsErrorMessage(message=f"Retrieval failed: {str(e)}")
                await websocket.send_json(error_msg.model_dump())
            except Exception as e:
                logger.error("WebSocket unexpected error: %s", e)
                error_msg = WsErrorMessage(message="An unexpected error occurred")
                await websocket.send_json(error_msg.model_dump())

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        try:
            error_msg = WsErrorMessage(message="Connection error")
            await websocket.send_json(error_msg.model_dump())
        except Exception:
            pass
