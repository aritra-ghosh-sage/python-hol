"""Main entry point demonstrating the hybrid RAG library usage."""

import logging
import sys

from hybrid_rag import (
    HybridRetriever,
    HybridRetrieverConfig,
    initialize_vector_db,
    get_sample_documents,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    """Main function demonstrating hybrid RAG retrieval.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    try:
        # Initialize vector database with sample documents
        logger.info("Initializing vector database...")
        documents = get_sample_documents()
        collection = initialize_vector_db(documents)

        # Create retriever with custom configuration
        config = HybridRetrieverConfig(
            semantic_weight=0.7,
            keyword_weight=0.3,
            enable_rerank=True,
        )
        retriever = HybridRetriever(collection, config)
        logger.info("✓ Hybrid retriever initialized successfully")

        # Example queries
        queries = [
            "How do I get started with Google Maps?",
            "How do I update a location or edit a review on google map?",
            "Can I use maps offline?",
        ]

        # Execute retrievals
        for query in queries:
            logger.info(f"\nQuery: {query}")
            logger.info("-" * 60)

            try:
                results = retriever.retrieve(query)

                if not results:
                    logger.warning("No results found")
                    continue

                for i, result in enumerate(results, 1):
                    logger.info(
                        f"{i}. Score: {result['score']:.3f} | "
                        f"Source: {result['metadata']['source']}"
                    )
                    logger.info(f"   Text: {result['text'][:80]}...")

            except Exception as e:
                logger.error(f"Retrieval failed: {e}", exc_info=True)
                return 1

        # Demonstrate configuration update
        logger.info("\n" + "=" * 60)
        logger.info("Demonstrating Configuration Update")
        logger.info("=" * 60)

        logger.info(f"Original config: semantic_weight={retriever.config.semantic_weight}, keyword_weight={retriever.config.keyword_weight}")

        # Update configuration
        try:
            updated_config = retriever.update_config(
                semantic_weight=0.8,
                keyword_weight=0.2,
                enable_rerank=False,
            )
            logger.info("✓ Configuration updated successfully")
            logger.info(
                f"New config: semantic_weight={updated_config.semantic_weight}, "
                f"keyword_weight={updated_config.keyword_weight}, "
                f"enable_rerank={updated_config.enable_rerank}"
            )

            # Retrieve with updated config
            logger.info("\nRetrieving with updated configuration...")
            results = retriever.retrieve("How do I use maps offline?")
            logger.info(f"Retrieved {len(results)} results with updated config")

        except ValueError as e:
            logger.error(f"Configuration update failed: {e}")
            return 1

        logger.info("\n✓ All retrievals and config updates completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
