"""Example usage of the Hybrid RAG library for document retrieval.

This script demonstrates how to use the hybrid RAG library to perform
semantic and keyword-based document retrieval with optional reranking.
"""

from hybrid_rag import (
    HybridRetriever,
    HybridRetrieverConfig,
    MIN_SCORE_RETRIEVAL,
    initialize_vector_db,
    get_sample_documents,
)

# Initialize vector database with sample documents
collection = initialize_vector_db(get_sample_documents())

# Create retriever with custom configuration
config = HybridRetrieverConfig(
    semantic_weight=0.7,
    keyword_weight=0.3,
    enable_rerank=True,
)

retriever = HybridRetriever(collection, config)

# Perform retrieval
results = retriever.retrieve("How do I update a location or edit a review on google map?")

# Display results
print("\n--- Hybrid Retrieval Results ---\n")

for r in results:
    if r["score"] >= MIN_SCORE_RETRIEVAL:
        print(
            f"{r['score']:.3f} | {r['metadata']['source']} | {r['text'][:80]}"
        )
    else:
        print(f"Unmatched data: {r['text'][:80]}, Score: {r['score']:.3f}")
