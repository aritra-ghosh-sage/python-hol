# Release Team Setup Guide - Hybrid RAG Solution

This document provides instructions for the release team to set up and validate the Hybrid RAG solution in a cloud environment.

## 1. Prerequisites

- **Python**: 3.13+
- **UV**: Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Memory**: 8GB+ (for local model execution)
- **Disk**: 5GB+ (for models and knowledge base)
- **Setup GitRepo**: `git clone git@github.com:aritra-ghosh-sage/python-hol.git`

## 2. Environment Setup

Navigate to the project root directory (e.g. `python-hol`).

### Initialize Python Environment
```bash
# Install dependencies using uv
uv sync
```

### Configure Environment Variables
Create a `.env` file in the project root with the following configuration:

```env
# Server Configuration
MCP_HOST=0.0.0.0
MCP_PORT=8001
MCP_TRANSPORT=http

# App Configuration
COLLECTION_NAME=rag_collection
KNOWLEDGE_DB_DIRECTORY=./knowledge_db

# Caching (L1 - Shared Response Cache)
CACHE_BACKEND=memory
CACHE_TTL_SECONDS=3600
CACHE_MAX_SIZE=10000

# Logging
LOG_LEVEL=INFO
```

## 3. Resource Resolution (Models & Knowledge Base)

The solution requires pre-trained models and a vector database. These are provided in the `\backup` directory.

### Restore Vector Database (Knowledge Base)
```bash
# Assumption: The folder `backup` exists under the root-app and has a file with the signature db_<mm_dd_yy_HH_MM_SS>.bak
# This restores the latest database backup (db_*.bak) into ./knowledge_db
uv run python tools/collections_cli.py restore --force
```

### Restore Embedding Models (Sentence Transformers)
```bash
# Assumption: The folder `backup` exists under the root-app and has a file with the signature st_<mm_dd_yy_HH_MM_SS>.bak
# This restores the latest sentence-transformer backup (st_*.bak)
uv run python tools/collections_cli.py model-restore st --force
```

### Restore Reranker Models (Cross Encoders)
```bash
# Assumption: The folder `backup` exists under the root-app and has a file with the signature ce_<mm_dd_yy_HH_MM_SS>.bak
# This restores the latest cross-encoder backup (ce_*.bak)
uv run python tools/collections_cli.py model-restore ce --force
```

## 4. Starting the Service

The solution is a FastAPI backend. Start it using `uvicorn`:

```bash
uv run uvicorn api:app --host 0.0.0.0 --port 8000
```

---

## 5. Post-Setup Sanity Test

Execute these checks to ensure the solution is functioning correctly.

### Check 1: Health Endpoint
Verify the service is live and the retriever is initialized.
```bash
curl http://localhost:8001/health
```
**Expected Output:** `{"status": "healthy", "retriever_ready": "yes"}`

### Check 2: Configuration Validation
Ensure the collection name and persistence paths are correctly loaded.
```bash
curl http://localhost:8001/config
```
**Expected Output:** JSON containing `collection_name: "rag_collection"` and correct model paths.

### Check 3: Retrieval Verification (WebSocket)
Test the end-to-end retrieval flow against the backend websocket on port `8001`.

```bash
# Run the bundled sanity check script.
uv run python sanity_check.py
```
**Expected Output:** The script prints passing REST checks and a WebSocket result payload with returned documents.

### Check 4: Knowledge Base Inspection
Verify collections are visible via the CLI.
```bash
uv run python tools/collections_cli.py status
```
**Expected Output:** A table showing the `rag_collection` with a non-zero document count and no corruption issues.

### Manage Collections via CLI
The `collections_cli.py` script provides commands to manage ChromaDB collections. Below are the available commands:

#### List Collections
```bash
uv run python tools/collections_cli.py list
```
**Expected Output:** A list of available collections with their document counts.

#### Add a New Collection
```bash
uv run python tools/collections_cli.py add <collection_name>
```
Replace `<collection_name>` with the desired name for the new collection.

#### Delete a Collection
```bash
uv run python tools/collections_cli.py delete <collection_name> --force
```
Use the `--force` flag to skip confirmation prompts.

#### Backup a Collection
```bash
uv run python tools/collections_cli.py backup --backup-dir ./backup
```
This creates a timestamped backup of the active collection in the specified directory.

#### Restore a Collection
```bash
uv run python tools/collections_cli.py restore --force
```
Restores the latest backup of the vector database.

#### Backup Models
```bash
uv run python tools/collections_cli.py model-backup st --backup-dir ./backup
uv run python tools/collections_cli.py model-backup ce --backup-dir ./backup
```
Backs up sentence-transformer (`st`) and cross-encoder (`ce`) models.

#### Restore Models
```bash
uv run python tools/collections_cli.py model-restore st --force
uv run python tools/collections_cli.py model-restore ce --force
```
Restores the latest backups for sentence-transformer and cross-encoder models.
