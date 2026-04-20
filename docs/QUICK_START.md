"""Quick Start Guide for Hybrid RAG Library

Fast-track guide to using the refactored hybrid RAG library.
"""

# Quick Start Guide - Hybrid RAG Library

## Installation

Ensure you have Python 3.9+ and installed dependencies:

```bash
# If using uv
uv pip install chromadb sentence-transformers fastapi uvicorn langchain_text_splitters

# Or with pip
pip install chromadb sentence-transformers fastapi uvicorn langchain_text_splitters
```

## Basic Usage

### 1. Initialize the Library

```python
from hybrid_rag import (
    HybridRetriever,
    HybridRetrieverConfig,
    initialize_vector_db,
    get_sample_documents,
)

# Load documents
documents = get_sample_documents()

# Initialize vector database
collection = initialize_vector_db(documents)

# Create configuration
config = HybridRetrieverConfig(
    semantic_weight=0.7,      # Weight for semantic search
    keyword_weight=0.3,        # Weight for keyword search
    enable_rerank=True,        # Use cross-encoder reranking
)

# Create retriever
retriever = HybridRetriever(collection, config)
```

### 2. Run Retrieval

```python
# Simple retrieval
results = retriever.retrieve("How do I use offline maps?")

# Process results
for result in results:
    print(f"Score: {result['score']:.3f}")
    print(f"Source: {result['metadata']['source']}")
    print(f"Text: {result['text'][:100]}...")
```

### 3. Process Custom Documents

```python
# Your custom documents
my_docs = [
    {
        "id": "1",
        "source": "https://example.com/doc1",
        "text": "Document text content here...",
    },
    # More documents...
]

# Initialize with custom documents
collection = initialize_vector_db(
    my_docs,
    persist_dir="./my_custom_db"
)
```

## Using the FastAPI REST API

### Start the API Server

```bash
source .venv/bin/activate
python api.py
```

The server starts at `http://localhost:8000`

### API Endpoints

#### 1. Health Check
```bash
curl http://localhost:8000/health
# Response:
# {"status": "healthy", "retriever_ready": "yes"}
```

#### 2. Retrieve Documents
```bash
curl -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How do I use offline maps?",
    "enable_rerank": true
  }'
```

#### 3. Retrieve with Score Filtering
```bash
curl -X POST 'http://localhost:8000/retrieve-filtered?min_score=0.8' \
  -H "Content-Type: application/json" \
  -d '{"query": "Your search query"}'
```

#### 4. Get Configuration
```bash
curl http://localhost:8000/config
```

### API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Configuration Options

### HybridRetrieverConfig Parameters

```python
config = HybridRetrieverConfig(
    # Semantic search (embedding-based)
    semantic_top_k=10,           # Results to get from semantic search
    semantic_weight=0.65,        # Weight for semantic search (0-1)
    
    # Keyword search
    keyword_top_k=10,            # Results to get from keyword search
    keyword_weight=0.35,         # Weight for keyword search (0-1)
    
    # Reranking
    enable_rerank=True,          # Enable cross-encoder reranking
    pre_rerank_top_k=50,         # Candidates to consider for reranking
    
    # Output
    final_top_k=5,               # Maximum results to return
)
```

**Note**: `semantic_weight + keyword_weight` must equal 1.0

## Error Handling

The library defines custom exceptions:

```python
from hybrid_rag import (
    HybridRAGException,
    RetrievalError,
    VectorDBError,
)

try:
    results = retriever.retrieve(query)
except RetrievalError as e:
    print(f"Retrieval failed: {e}")
except VectorDBError as e:
    print(f"Database error: {e}")
except HybridRAGException as e:
    print(f"Library error: {e}")
```

## Logging

Configure logging to debug issues:

```python
import logging

# Set log level
logging.basicConfig(
    level=logging.DEBUG,  # Or INFO, WARNING, ERROR
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Log specific library
logger = logging.getLogger('hybrid_rag')
logger.setLevel(logging.DEBUG)
```

## Advanced Usage

### Custom Vector DB Location

```python
collection = initialize_vector_db(
    documents,
    persist_dir="./my_embeddings",
    collection_name="my_collection"
)
```

### Fine-tune Weights for Your Use Case

```python
# More semantic (meaning-based)
config = HybridRetrieverConfig(
    semantic_weight=0.8,
    keyword_weight=0.2,
)

# More keyword-focused (exact matches)
config = HybridRetrieverConfig(
    semantic_weight=0.5,
    keyword_weight=0.5,
)

# Disable reranking for speed
config = HybridRetrieverConfig(
    enable_rerank=False,
)
```

### Override Reranking Per Query

```python
from hybrid_rag.config import HybridRetrieverConfig

# Default enabled
config = HybridRetrieverConfig(enable_rerank=True)

# But the API allows override:
# POST /retrieve with enable_rerank: false to skip reranking
```

## Example Scripts

### Script 1: Simple Retrieval (main_example.py)
```bash
source .venv/bin/activate
python main_example.py
```

### Script 2: API Server (api.py)
```bash
source .venv/bin/activate
python api.py
```

### Script 3: Demo Retrieval (hybrid_rag_flow.py)
```bash
source .venv/bin/activate
python hybrid_rag_flow.py
```

## Performance Tips

1. **Reranking**: Disable for real-time applications
   ```python
   config.enable_rerank = False
   ```

2. **Top-k Values**: Reduce for faster retrieval
   ```python
   config.semantic_top_k = 5  # Instead of 10
   ```

3. **Batch Queries**: Process multiple queries together
   ```python
   queries = ["query1", "query2", "query3"]
   results_list = [retriever.retrieve(q) for q in queries]
   ```

4. **Cache Results**: For repeated queries, cache results externally

## Common Issues

### Issue: Embedding Download Fails
**Solution**: Ensure internet connection. Models download automatically on first run.

### Issue: CrossEncoder Not Available
**Solution**: Will fallback gracefully - reranking disabled but retrieval still works

### Issue: Memory Usage High
**Solution**: Reduce top-k values or process documents in batches

### Issue: Slow Retrieval
**Solution**: 
- Disable reranking: `enable_rerank=False`
- Reduce top-k values
- Use fewer documents

## Testing

Basic test of functionality:

```python
from hybrid_rag import HybridRetriever, initialize_vector_db, get_sample_documents

# Setup
docs = get_sample_documents()
collection = initialize_vector_db(docs)
retriever = HybridRetriever(collection)

# Test retrieval
results = retriever.retrieve("test query")
assert len(results) > 0
assert all("score" in r for r in results)
assert all(0 <= r["score"] <= 1 for r in results)

print("✓ Library working correctly!")
```

## Additional Resources

- **Design Documentation**: See [LIBRARY_DESIGN.md](LIBRARY_DESIGN.md)
- **Refactoring Summary**: See [REFACTORING_SUMMARY.md](REFACTORING_SUMMARY.md)
- **API Documentation**: http://localhost:8000/docs (when running api.py)

## Next Steps

1. ✅ Read the API documentation at `/docs`
2. ✅ Try custom documents
3. ✅ Experiment with configuration parameters
4. ✅ Deploy the REST API
5. ✅ Integrate into your application

---

**Happy retrieving! 🚀**
