"""Constants and default configuration for the hybrid RAG library.

Note 1: Centralizing constants in a dedicated module is a key maintainability
pattern. It creates a single source of truth — changing a value here propagates
everywhere it is imported, preventing the "magic number" anti-pattern where the
same literal (e.g. 0.80) appears scattered across many files.
"""

# Note 2: __all__ controls what `from hybrid_rag.constants import *` exports.
# More importantly, it signals to readers (and tools like IDEs) which names are
# part of the public API. Internal helpers that should not be imported by
# consumers are simply omitted from this list.
__all__ = [
    "KNOWLEDGE_DB_DIRECTORY",
    "MIN_RELEVANCE_SCORE",
    "STOP_WORDS",
    "CACHE_TELEMETRY_LABELS",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_MODEL_PATH",
    "DEFAULT_RERANKER_MODEL_PATH",
    "COLLECTION_NAME_INVALID_MSG",
]

# Note 3: Using a relative path ("./knowledge_db") means the database is created
# relative to the process working directory. This is convenient for development
# and local testing, but production deployments should override this with an
# absolute path via the persist_dir argument to initialize_vector_db().
# Default directory for persisting ChromaDB collections
KNOWLEDGE_DB_DIRECTORY = "./knowledge_db"

# Single source of truth for the collection-name validation error message.
# Referenced by is_valid_collection_name callers so the constraint is stated once.
COLLECTION_NAME_INVALID_MSG = "must be 6-20 chars, alphanumeric/underscore/hyphen only"

# Note 4: This constant was changed from "all-MiniLM-L6-v2" to
# "BAAI/bge-small-en-v1.5" as part of ADR-0001 (EMB-006). The key reasons:
#   - MTEB retrieval score: 51.68 vs ~41-42 (roughly a 25% improvement).
#   - Effective token window: 512 tokens vs ~128 tokens — eliminates silent
#     tail truncation that degraded embedding quality for long chunks.
#   - Output dimensionality is identical (384-dim), so no ChromaDB HNSW index
#     schema migration is required when switching models.
# Important: persisted collections embedded with a previous model will still
# load because the dimensionality matches, but their vectors are not
# semantically comparable to query embeddings produced by the new model.
# Re-embed or rebuild existing collections after changing
# DEFAULT_EMBEDDING_MODEL to avoid silent retrieval quality regressions.
# Note 5: The model name follows the Hugging Face Hub convention
# "organisation/model-name". sentence-transformers downloads the model weights
# from the Hub on first use and caches them locally (~130 MB for bge-small).
# Default sentence-transformer model for embeddings.
# Upgraded from all-MiniLM-L6-v2: MTEB retrieval 51.68 vs 41-42, 512-token window.
# Output dimensionality remains 384-dim, but existing persisted collections
# must be re-embedded/rebuilt after changing the embedding model.
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# Local model cache paths: the sentence-transformer embedding model and the
# cross-encoder reranker model are downloaded from Hugging Face on first use
# and persisted to these directories. All subsequent initializations load from
# disk, removing any dependency on the Hugging Face endpoint during inference.
# Override via HybridRetrieverConfig(embedding_model_path=..., reranker_model_path=...)
# or the corresponding config-file mechanism used by the application.
DEFAULT_EMBEDDING_MODEL_PATH = "./models/embedding"
DEFAULT_RERANKER_MODEL_PATH = "./models/reranker"

# Note 6: MIN_RELEVANCE_SCORE acts as a quality gate. The retriever discards
# any candidate document whose combined hybrid score falls below this threshold
# before returning results to the caller. Setting it too high may produce empty
# result sets; too low lets low-quality matches through. 0.80 is a reasonable
# starting point for cosine-distance-based similarity scores (which range 0–1).
# Minimum relevance score threshold for retrieved documents
MIN_RELEVANCE_SCORE = 0.80

# Note 7: STOP_WORDS defines a manually curated set of English words that
# carry little or no semantic meaning (articles, conjunctions, pronouns).
# The keyword scoring stage (BM25-style) skips these tokens when computing
# term frequency overlap. Storing them as a Python `set` gives O(1) membership
# tests via hash lookup — much faster than scanning a list for every token.
# Stop words to exclude from keyword scoring
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "its", "be", "as", "are",
    "was", "were", "been", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can", "how",
    "what", "where", "when", "who", "which", "that", "this", "these",
    "those", "not", "no", "so", "if", "about", "up", "out", "i", "my",
}

# Note 8: CACHE_TELEMETRY_LABELS maps short logical event names to their
# string label equivalents. Using a dictionary of named constants here — rather
# than scattering raw strings like "cache.retrieval_hit" across multiple files —
# means that if the label format ever changes (e.g., switching from dot-notation
# to slash-notation), only this file needs to be updated.
# Note 9: The "cache." prefix groups all cache-related events together in
# monitoring dashboards and log aggregators, making it easy to filter and alert
# on cache behaviour independently of other application events.
# T03: Structured telemetry event labels for cache observability (RSK-001).
# Defined here as named constants so dashboards and alert rules can reference
# a single authoritative source and refactors never silently break label
# matching.
CACHE_TELEMETRY_LABELS = {
    # Retrieval layer — emitted by _shared_retrieve_documents
    "retrieval_hit": "cache.retrieval_hit",
    "retrieval_miss": "cache.retrieval_miss",
    "retrieval_error": "cache.retrieval_error",
    # Backend health transitions — emitted by _log_fallback_transition
    "fallback_activated": "cache.fallback_activated",
    "fallback_deactivated": "cache.fallback_deactivated",
}
