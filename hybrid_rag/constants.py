"""Constants and default configuration for the hybrid RAG library."""

__all__ = ["DEFAULT_PERSIST_DIRECTORY", "MIN_RELEVANCE_SCORE", "STOP_WORDS"]

# Default directory for persisting ChromaDB collections
DEFAULT_PERSIST_DIRECTORY = "./ai_support_kb"

# Minimum relevance score threshold for retrieved documents
MIN_RELEVANCE_SCORE = 0.95

# Stop words to exclude from keyword scoring
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "its", "be", "as", "are",
    "was", "were", "been", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can", "how",
    "what", "where", "when", "who", "which", "that", "this", "these",
    "those", "not", "no", "so", "if", "about", "up", "out", "i", "my",
}
