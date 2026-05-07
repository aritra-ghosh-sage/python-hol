from hybrid_rag.cache_utils import build_corpus_version_token, build_shared_retrieve_cache_key


class MockCollection:
    """Mock ChromaDB collection for testing."""
    def __init__(self, count: int):
        self._count = count

    def count(self) -> int:
        return self._count


class MockRetriever:
    """Mock retriever with collection."""
    def __init__(self, collection: MockCollection):
        self.collection = collection


def test_build_corpus_version_token_with_retriever():
    """Corpus version token should encode generation + collection count."""
    retriever = MockRetriever(MockCollection(42))
    token = build_corpus_version_token(retriever, cache_generation=5)
    assert token == "gen5.n42"


def test_build_corpus_version_token_with_none_retriever():
    """Corpus version token should fall back to gen{N}.n0 when retriever is None."""
    token = build_corpus_version_token(None, cache_generation=5)
    assert token == "gen5.n0"


def test_build_corpus_version_token_with_collection_error():
    """Corpus version token should fall back gracefully if collection.count() raises."""
    class FailingCollection:
        def count(self):
            raise RuntimeError("DB connection failed")

    retriever = MockRetriever(FailingCollection())
    token = build_corpus_version_token(retriever, cache_generation=3)
    assert token == "gen3.n0"


def test_build_shared_retrieve_cache_key_consistency():
    """Both api.py and mcp_server.py should build identical cache keys for same inputs."""
    corpus_version = "gen0.n100"

    config = {
        "semantic_top_k": 5,
        "keyword_top_k": 5,
        "final_top_k": 10,
        "semantic_weight": 0.5,
        "keyword_weight": 0.5,
        "enable_rerank": True,
        "pre_rerank_top_k": 50,
    }

    key = build_shared_retrieve_cache_key(
        query="what is retrieval augmented generation",
        config_dict=config,
        corpus_version=corpus_version,
        enable_rerank=True,
    )

    # Key should have consistent format
    assert key.startswith("shared-retrieve:")
    assert len(key) == len("shared-retrieve:") + 64  # SHA-256 hex digest is 64 chars


def test_build_shared_retrieve_cache_key_with_whitespace_normalization():
    """Cache key should normalize query whitespace."""
    corpus_version = "gen0.n100"
    config = {
        "semantic_top_k": 5,
        "keyword_top_k": 5,
        "final_top_k": 10,
        "semantic_weight": 0.5,
        "keyword_weight": 0.5,
        "enable_rerank": True,
        "pre_rerank_top_k": 50,
    }

    key1 = build_shared_retrieve_cache_key(
        query="what    is  RAG",
        config_dict=config,
        corpus_version=corpus_version,
        enable_rerank=True,
    )

    key2 = build_shared_retrieve_cache_key(
        query="what is RAG",
        config_dict=config,
        corpus_version=corpus_version,
        enable_rerank=True,
    )

    # Different whitespace should not affect key
    assert key1 == key2


def test_build_shared_retrieve_cache_key_varies_with_config():
    """Cache key should change when config changes."""
    corpus_version = "gen0.n100"
    query = "test query"
    enable_rerank = True

    config1 = {
        "semantic_top_k": 5,
        "keyword_top_k": 5,
        "final_top_k": 10,
        "semantic_weight": 0.5,
        "keyword_weight": 0.5,
        "enable_rerank": True,
        "pre_rerank_top_k": 50,
    }

    config2 = {
        "semantic_top_k": 10,  # changed
        "keyword_top_k": 5,
        "final_top_k": 10,
        "semantic_weight": 0.5,
        "keyword_weight": 0.5,
        "enable_rerank": True,
        "pre_rerank_top_k": 50,
    }

    key1 = build_shared_retrieve_cache_key(query, config1, corpus_version, enable_rerank)
    key2 = build_shared_retrieve_cache_key(query, config2, corpus_version, enable_rerank)

    assert key1 != key2
