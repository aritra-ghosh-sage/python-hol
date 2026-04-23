"""Constants and default configuration for the hybrid RAG library."""

__all__ = [
    "DEFAULT_PERSIST_DIRECTORY",
    "MIN_RELEVANCE_SCORE",
    "STOP_WORDS",
    "CACHE_TELEMETRY_LABELS",
]

# Default directory for persisting ChromaDB collections
DEFAULT_PERSIST_DIRECTORY = "./ai_support_kb"

# Minimum relevance score threshold for retrieved documents
MIN_RELEVANCE_SCORE = 0.80

# Stop words to exclude from keyword scoring
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "its", "be", "as", "are",
    "was", "were", "been", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can", "how",
    "what", "where", "when", "who", "which", "that", "this", "these",
    "those", "not", "no", "so", "if", "about", "up", "out", "i", "my",
}

# T03: Structured telemetry event labels for cache observability (RSK-001).
# Defined here as named constants so dashboards and alert rules can reference
# a single authoritative source and refactors never silently break label
# matching.  Both HTTP-layer (middleware) and retrieval-layer events are
# included so the full observability contract is captured in one place.
CACHE_TELEMETRY_LABELS = {
    # HTTP middleware layer — emitted by QueryCacheMiddleware
    "http_hit": "cache.http_hit",
    "http_miss": "cache.http_miss",
    # Retrieval layer — emitted by _shared_retrieve_documents
    "retrieval_hit": "cache.retrieval_hit",
    "retrieval_miss": "cache.retrieval_miss",
    "retrieval_error": "cache.retrieval_error",
    # Backend health transitions — emitted by _log_fallback_transition
    "fallback_activated": "cache.fallback_activated",
    "fallback_deactivated": "cache.fallback_deactivated",
}
