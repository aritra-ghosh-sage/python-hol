"""WebSocket chat endpoint.

Routes:
    WS /ws/chat  -- Real-time document query stream.

Protocol (client → server):
    {"query": str, "enable_rerank": bool | null}

Protocol (server → client, in order):
    {"type": "status",  "message": str}
    {"type": "results", "query": str, "results": [...],
     "total_results": int, "cache_status": "HIT"|"MISS"|"ERROR"}
    {"type": "error",   "message": str}   (on failure)
"""

import uuid
from typing import Literal

import api  # shared state — accessed inside function bodies to avoid circular-import issues
from api_models import (
    DocumentResult,
    WsErrorMessage,
    WsResultsMessage,
    WsStatusMessage,
)
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from hybrid_rag import RetrievalError

router = APIRouter()


def _to_filtered_document_results(
    results: list[dict],
    min_score_threshold: float,
) -> list[DocumentResult]:
    """Filter retrieval results and convert them to API response models.

    Args:
        results: Raw retrieval results from the HybridRetriever.
        min_score_threshold: Minimum relevance score to include in output.

    Returns:
        Filtered list of DocumentResult instances.
    """
    filtered = [r for r in results if float(r.get("score", 0.0)) >= min_score_threshold]
    api.logger.debug(
        "Filtered from %d to %d results (min_score=%s)",
        len(results),
        len(filtered),
        min_score_threshold,
    )
    return [
        DocumentResult(
            id=r["id"],
            text=r["text"],
            source=r["metadata"]["source"],
            source_url=r["metadata"].get("source_url"),
            score=float(r["score"]),
        )
        for r in filtered
    ]


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time document queries.

    Client sends: ``{"query": str, "enable_rerank": bool | null}``

    Server sends (in sequence):
        - ``{"type": "status", "message": str}``
        - ``{"type": "results", "query": str, "results": [...],
             "total_results": int, "cache_status": "HIT"|"MISS"|"ERROR"}``
        - ``{"type": "error", "message": str}`` (on failure)

    Args:
        websocket: Active WebSocket connection.
    """
    await websocket.accept()
    api.logger.info("WebSocket client connected")

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
                results = api._shared_retrieve_documents(
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
                api.logger.info(
                    "WebSocket query succeeded: %s... (%d results after filtering)",
                    query[:50],
                    len(doc_results),
                )

            except RetrievalError as exc:
                api.logger.error("WebSocket retrieval error: %s", exc)
                error_msg = WsErrorMessage(message=f"Retrieval failed: {str(exc)}")
                await websocket.send_json(error_msg.model_dump())
            except Exception as exc:
                api.logger.error("WebSocket unexpected error: %s", exc)
                error_msg = WsErrorMessage(message="An unexpected error occurred")
                await websocket.send_json(error_msg.model_dump())

    except WebSocketDisconnect:
        api.logger.info("WebSocket client disconnected")
    except Exception as exc:
        api.logger.error("WebSocket error: %s", exc)
        try:
            error_msg = WsErrorMessage(message="Connection error")
            await websocket.send_json(error_msg.model_dump())
        except Exception:
            pass
