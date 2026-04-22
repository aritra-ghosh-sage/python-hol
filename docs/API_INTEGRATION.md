"""API Integration Guide - Hybrid RAG Retrieval Service

This document describes the complete REST API and WebSocket contracts for the
Hybrid RAG Retrieval Service, enabling frontend integration and third-party clients.
"""

# API Integration Guide - Hybrid RAG Retrieval Service

## Overview

The Hybrid RAG Retrieval Service exposes a production-ready REST API (`api.py`) that wraps the core Python library with:
- **REST endpoints** for retrieval, configuration, document management
- **WebSocket support** for real-time chat with status and results messages
- **Request/response validation** using Pydantic models
- **Comprehensive error handling** with meaningful HTTP status codes
- **CORS support** configured via `CORS_ORIGINS` environment variable

## API Base Configuration

| Property | Value |
|----------|-------|
| **Title** | Hybrid RAG Retriever API |
| **Version** | 1.0.0 |
| **Documentation URL** | `GET /docs` (Swagger UI) |
| **OpenAPI Schema** | `GET /openapi.json` |
| **Default CORS Origins** | `http://localhost:3000`, `http://localhost:3001` |
| **CORS Configuration** | Environment variable: `CORS_ORIGINS` (comma-separated) |

**Starting the API:**
```bash
# Activate environment and start server
source .venv/bin/activate
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

---

## REST Endpoints

### 1. Health Check

**Endpoint:** `GET /health`

**Purpose:** Verify service availability and retriever initialization status.

**Response Model:**
```typescript
{
  status: string;           // Always "healthy" if endpoint responds
  retriever_ready: string;  // "yes" or "no"
}
```

**Status Codes:**
- `200 OK` - Service healthy

**Example:**
```bash
curl -X GET http://localhost:8000/health
```

**Response:**
```json
{
  "status": "healthy",
  "retriever_ready": "yes"
}
```

---

### 2. Document Retrieval

**Endpoint:** `POST /retrieve`

**Purpose:** Retrieve relevant documents using hybrid search (semantic + keyword). The current implementation filters results using a minimum score threshold of **0.80**.

**Request Model:**
```typescript
{
  query: string;                    // Search query (1-500 chars, required)
  enable_rerank?: boolean;          // Override reranking setting (optional)
}
```

**Response Model:**
```typescript
{
  query: string;                    // Original search query
  results: Array<{
    id: string;                     // Document identifier
    text: string;                   // Document content
    source: string;                 // Source URL or label
    score: float;                   // Relevance score (may be negative after fusion)
  }>;
  total_results: number;            // Count of results after filtering
}
```

**Status Codes:**
- `200 OK` - Retrieval successful
- `400 Bad Request` - Invalid query (validation error)
- `500 Internal Server Error` - Retrieval failed
- `503 Service Unavailable` - Retriever not initialized

**Example:**
```bash
curl -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How do I download maps for offline use?",
    "enable_rerank": true
  }'
```

**Response:**
```json
{
  "query": "How do I download maps for offline use?",
  "results": [
    {
      "id": "doc_001",
      "text": "Offline maps can be downloaded directly from the Maps app...",
      "source": "https://maps.google.com/help/offline",
      "score": 0.95
    },
    {
      "id": "doc_002",
      "text": "To download a map area for offline access...",
      "source": "https://maps.google.com/help/offline",
      "score": 0.92
    }
  ],
  "total_results": 2
}
```

---

### 3. Filtered Document Retrieval

**Endpoint:** `POST /retrieve-filtered?min_score=0.5`

**Purpose:** Retrieve documents with custom minimum relevance score filtering. **Note:** The API currently enforces a floor of **0.80**, so `min_score` is clamped to at least 0.80.

**Query Parameters:**
- `min_score` (optional, float): Minimum relevance score for filtering (0.0-1.0). Default: 0.5. Actual floor: 0.80.

**Request Model:**
```typescript
{
  query: string;                    // Search query (1-500 chars)
  enable_rerank?: boolean;          // Override reranking (optional)
}
```

**Response Model:** Same as `/retrieve`

**Status Codes:**
- `200 OK` - Retrieval successful
- `400 Bad Request` - Invalid min_score (outside 0-1 range)
- `500 Internal Server Error` - Retrieval failed
- `503 Service Unavailable` - Retriever not initialized

**Example:**
```bash
curl -X POST "http://localhost:8000/retrieve-filtered?min_score=0.8" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is RAG?"}'
```

---

### 4. Get Configuration

**Endpoint:** `GET /config`

**Purpose:** Retrieve the current retriever configuration parameters.

**Response Model:**
```typescript
{
  semantic_top_k: number;           // Results from semantic search
  keyword_top_k: number;            // Results from keyword search
  final_top_k: number;              // Final results to return after fusion
  semantic_weight: float;           // Weight for semantic search (0-1)
  keyword_weight: float;            // Weight for keyword search (0-1)
  enable_rerank: boolean;           // Cross-encoder reranking enabled
  pre_rerank_top_k: number;         // Candidates to consider before reranking
}
```

**Status Codes:**
- `200 OK` - Configuration retrieved
- `503 Service Unavailable` - Retriever not initialized

**Example:**
```bash
curl -X GET http://localhost:8000/config
```

**Response:**
```json
{
  "semantic_top_k": 10,
  "keyword_top_k": 10,
  "final_top_k": 5,
  "semantic_weight": 0.7,
  "keyword_weight": 0.3,
  "enable_rerank": true,
  "pre_rerank_top_k": 15
}
```

---

### 5. Update Configuration

**Endpoint:** `PUT /config`

**Purpose:** Update retriever configuration settings. Only provided fields are updated. All fields are optional (partial updates supported).

**Validation Rules:**
- `semantic_weight + keyword_weight` must equal 1.0 (±0.01 tolerance for floating point)
- All `*_top_k` values must be > 0
- Weights must be in range [0.0, 1.0]

**Request Model:**
```typescript
{
  semantic_top_k?: number;          // (optional) > 0
  keyword_top_k?: number;           // (optional) > 0
  final_top_k?: number;             // (optional) > 0
  semantic_weight?: float;          // (optional) 0.0-1.0
  keyword_weight?: float;           // (optional) 0.0-1.0
  enable_rerank?: boolean;          // (optional)
  pre_rerank_top_k?: number;        // (optional) > 0
}
```

**Response Model:** Same as `GET /config` (returns updated configuration)

**Status Codes:**
- `200 OK` - Configuration updated
- `400 Bad Request` - Validation error (invalid weights, out of range)
- `500 Internal Server Error` - Unexpected error during update
- `503 Service Unavailable` - Retriever not initialized

**Example: Update semantic weight**
```bash
curl -X PUT http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -d '{
    "semantic_weight": 0.8,
    "keyword_weight": 0.2
  }'
```

**Validation Error Example:**
```bash
curl -X PUT http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -d '{
    "semantic_weight": 0.8,
    "keyword_weight": 0.5
  }'
```

**Response (400 Bad Request):**
```json
{
  "detail": "Configuration validation failed: Weights must sum to 1.0, got 1.3"
}
```

---

### 6. Add Custom Documents

**Endpoint:** `POST /documents`

**Purpose:** Ingest custom documents from three sources: raw text, URLs, or file uploads (txt, md, pdf).

**Request Model:**
```typescript
{
  source_type: "text" | "url" | "file";  // Data source type
  content: string;                        // Text content, URL, or base64-encoded file
  filename?: string;                      // Original filename (for file uploads)
  source_label?: string;                  // User-friendly label for source
}
```

**Response Model:**
```typescript
{
  status: "success" | "error";            // Operation status
  documents_added: number;                // Count of documents added
  chunks_created: number;                 // Count of chunks created (after text splitting)
  message?: string;                       // Additional details
}
```

**Source Types:**

- **text**: Raw plaintext content
  ```typescript
  {
    "source_type": "text",
    "content": "Your document text here...",
    "source_label": "My Custom Document"
  }
  ```

- **url**: URL to fetch and ingest
  ```typescript
  {
    "source_type": "url",
    "content": "https://example.com/docs/page.html",
    "source_label": "External Documentation"
  }
  ```

- **file**: Base64-encoded file (txt, md, pdf)
  ```typescript
  {
    "source_type": "file",
    "content": "BASE64_ENCODED_FILE_CONTENT",
    "filename": "document.pdf",
    "source_label": "Uploaded PDF"
  }
  ```

**Status Codes:**
- `200 OK` - Documents ingested successfully
- `400 Bad Request` - Invalid file format or content
- `500 Internal Server Error` - Processing error
- `503 Service Unavailable` - Retriever not initialized

**Example: Add text document**
```bash
curl -X POST http://localhost:8000/documents \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "text",
    "content": "Maps allows you to download areas...",
    "source_label": "Custom Maps Guide"
  }'
```

**Response:**
```json
{
  "status": "success",
  "documents_added": 1,
  "chunks_created": 3,
  "message": "Document ingested and chunked successfully"
}
```

**Example: Upload PDF file**
```bash
# First, base64-encode the file
cat document.pdf | base64 > file_b64.txt

curl -X POST http://localhost:8000/documents \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "file",
    "content": "'$(cat file_b64.txt)'",
    "filename": "document.pdf",
    "source_label": "Company Handbook"
  }'
```

---

### 7. List Document Sources

**Endpoint:** `GET /documents/sources`

**Purpose:** Retrieve a list of all document sources currently indexed with chunk counts.

**Response Model:**
```typescript
{
  sources: Array<{
    source: string;                 // Source identifier
    count: number;                  // Number of chunks from this source
  }>;
}
```

**Status Codes:**
- `200 OK` - Sources retrieved
- `503 Service Unavailable` - Retriever not initialized

**Example:**
```bash
curl -X GET http://localhost:8000/documents/sources
```

**Response:**
```json
{
  "sources": [
    {
      "source": "https://maps.google.com/help/offline",
      "count": 25
    },
    {
      "source": "Custom Maps Guide",
      "count": 8
    }
  ]
}
```

---

## WebSocket Endpoint

### Real-Time Chat

**Endpoint:** `WS /ws/chat`

**Purpose:** Real-time bidirectional communication for document queries. Client sends queries, server streams responses.

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/chat');

ws.onopen = () => console.log('Connected');
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  // Handle message based on msg.type
};
ws.onerror = (error) => console.error('WebSocket error:', error);
ws.onclose = () => console.log('Disconnected');
```

#### Client → Server Message

**Query Request:**
```typescript
{
  query: string;                    // Search query (1-500 chars)
  enable_rerank?: boolean;          // Override reranking (optional)
}
```

**Example:**
```javascript
ws.send(JSON.stringify({
  query: "How do I share offline maps with others?",
  enable_rerank: true
}));
```

#### Server → Client Messages

**1. Status Message** (sent before retrieval)
```typescript
{
  type: "status";
  message: string;  // e.g., "Retrieving documents..."
}
```

**2. Results Message** (sent on success)
```typescript
{
  type: "results";
  query: string;
  results: Array<{
    id: string;
    text: string;
    source: string;
    score: float;
  }>;
  total_results: number;
}
```

**3. Error Message** (sent on failure)
```typescript
{
  type: "error";
  message: string;  // e.g., "Query must be between 1 and 500 characters"
}
```

**Example Flow:**
```javascript
ws.send(JSON.stringify({ query: "offline maps" }));

// Server response sequence:
// 1. {"type": "status", "message": "Retrieving documents..."}
// 2. {"type": "results", "query": "offline maps", "results": [...], "total_results": 2}

// On error:
// {"type": "error", "message": "Retrieval failed: ..."}
```

**Validation:**
- Query must be 1-500 characters
- Retriever must be initialized (returns error if not)
- Retrieval errors are caught and sent as error messages

---

## Error Handling

### HTTP Status Codes

| Code | Scenario |
|------|----------|
| `200 OK` | Successful request |
| `400 Bad Request` | Validation error (invalid query, bad config params) |
| `500 Internal Server Error` | Retrieval or processing error |
| `503 Service Unavailable` | Retriever not initialized or service not ready |

### Error Response Format

All error responses follow FastAPI's standard exception format:
```typescript
{
  detail: string;  // Error message
}
```

### Common Error Scenarios

**Retriever not initialized:**
```json
{
  "detail": "Retriever service not initialized. Try again later."
}
```

**Invalid query length:**
```json
{
  "detail": "Query must be between 1 and 500 characters"
}
```

**Configuration validation failed:**
```json
{
  "detail": "Configuration validation failed: Weights must sum to 1.0, got 1.3"
}
```

**Retrieval operation failed:**
```json
{
  "detail": "Retrieval failed: VectorDB operation timeout"
}
```

---

## Integration Patterns

### Frontend (React/Next.js)

**REST Endpoint Integration:**
```typescript
// src/lib/api.ts
export async function retrieveDocuments(query: string, enableRerank?: boolean) {
  const response = await fetch('http://localhost:8000/retrieve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, enable_rerank: enableRerank })
  });
  
  if (!response.ok) {
    throw new Error(`Retrieval failed: ${response.statusText}`);
  }
  
  return response.json();
}

export async function getConfig() {
  const response = await fetch('http://localhost:8000/config');
  if (!response.ok) throw new Error('Failed to fetch config');
  return response.json();
}

export async function updateConfig(updates: Partial<Config>) {
  const response = await fetch('http://localhost:8000/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates)
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail);
  }
  
  return response.json();
}
```

**WebSocket Integration:**
```typescript
// src/lib/ws.ts
export class ChatWebSocket {
  private ws: WebSocket;
  
  connect(url: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(url);
      this.ws.onopen = () => resolve();
      this.ws.onerror = (error) => reject(error);
    });
  }
  
  async sendQuery(query: string, enableRerank?: boolean): Promise<RetrievalResponse> {
    return new Promise((resolve, reject) => {
      let results: RetrievalResponse | null = null;
      
      const handleMessage = (event: MessageEvent) => {
        const msg = JSON.parse(event.data);
        
        if (msg.type === 'status') {
          console.log('Status:', msg.message);
        } else if (msg.type === 'results') {
          results = msg;
          this.ws.removeEventListener('message', handleMessage);
          resolve(results);
        } else if (msg.type === 'error') {
          this.ws.removeEventListener('message', handleMessage);
          reject(new Error(msg.message));
        }
      };
      
      this.ws.addEventListener('message', handleMessage);
      this.ws.send(JSON.stringify({ query, enable_rerank: enableRerank }));
    });
  }
  
  close() {
    this.ws.close();
  }
}

// Usage in React component
const [results, setResults] = useState<RetrievalResponse | null>(null);
const ws = useRef<ChatWebSocket | null>(null);

useEffect(() => {
  ws.current = new ChatWebSocket();
  ws.current.connect('ws://localhost:8000/ws/chat');
  
  return () => ws.current?.close();
}, []);

async function handleQuery(query: string) {
  try {
    const response = await ws.current.sendQuery(query);
    setResults(response);
  } catch (error) {
    console.error('Query failed:', error);
  }
}
```

### Environment Configuration

**Backend (.env):**
```bash
# CORS configuration for frontend
CORS_ORIGINS=http://localhost:3000,http://localhost:3001,https://yourdomain.com

# Logging
LOG_LEVEL=INFO
```

**Frontend (.env.local):**
```bash
# API configuration
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

---

## Performance Considerations

### Caching & Rate Limiting
- The API currently does **not implement rate limiting**. For production deployments, consider:
  - Redis-backed L1 query caching for repeated requests
  - Rate limiting middleware (e.g., `slowapi` for FastAPI)
  - Monitoring both L1 and L2 cache behavior through `/cache/stats`

### Score Thresholds
- **Default retrieval threshold:** 0.80 in `/retrieve`
- **Configurable threshold:** `min_score` in `/retrieve-filtered` is clamped to 0.80 minimum
- Results below the effective threshold are filtered out before response serialization

### Configuration Updates
- Configuration updates are **applied immediately** and affect subsequent queries
- The API temporarily overrides reranking when `enable_rerank` is provided in the request
- Changes persist until next update (configuration is mutable global state)

### WebSocket Real-Time Chat: Full Protocol Documentation

#### Connection Overview

The WebSocket endpoint provides real-time bidirectional communication for document queries with a simple status-then-results flow.

**URL Formats:**
- Development: `ws://localhost:8000/ws/chat`
- Production: `wss://your-domain.com/ws/chat` (TLS required)

#### Message Types & Schemas

All WebSocket messages are JSON objects with a required `type` field.

##### Client → Server: Query Request

```typescript
{
  type: "query";
  query: string;                    // Search query (1-500 chars, REQUIRED)
  enable_rerank?: boolean;          // Override config reranking (optional)
}
```

**Validation:**
- `query` is required and must be non-empty
- `query` length must be 1-500 characters
- Returns error if validation fails

**Example:**
```javascript
ws.send(JSON.stringify({
  type: "query",
  query: "How do I share offline maps with others?",
  enable_rerank: true
}));
```

##### Server → Client: Status Update

```typescript
{
  type: "status";
  message: string;                  // Status message
}
```

**Example:**
```json
{
  "type": "status",
  "message": "Retrieving documents..."
}
```

##### Server → Client: Results (Success)

```typescript
{
  type: "results";
  query: string;                    // Original query echo
  results: Array<{
    id: string;                     // Document ID
    text: string;                   // Document chunk text
    source: string;                 // Source URL or label
    score: number;                  // Relevance score (0-1 or negative after fusion)
  }>;
  total_results: number;            // Count of results returned
}
```

**Score Interpretation:**
- `score >= 0.80`: High confidence match under the default API threshold
- `score 0.5-0.80`: Moderate match (may still be filtered out by endpoint thresholds)
- Negative scores: possible after fusion, indicates keyword-heavy result

**Example:**
```json
{
  "type": "results",
  "query": "offline maps",
  "results": [
    {
      "id": "doc_001",
      "text": "Offline maps can be downloaded directly from the Maps app by tapping...",
      "source": "https://maps.google.com/help/offline",
      "score": 0.96
    }
  ],
  "total_results": 1
}
```

##### Server → Client: Error

```typescript
{
  type: "error";
  message: string;                  // Error message
  error_code?: string;              // Machine-readable code
  details?: string;                 // Additional details
  timestamp: string;                // ISO8601 timestamp
}
```

**Common Error Codes:**
- `VALIDATION_ERROR` - Input validation failed
- `RETRIEVER_NOT_READY` - Service not initialized
- `RETRIEVAL_FAILED` - Hybrid search error
- `RERANKING_FAILED` - Cross-encoder error
- `INVALID_MESSAGE` - Malformed message

**Example:**
```json
{
  "type": "error",
  "message": "Query must be between 1 and 500 characters",
  "error_code": "VALIDATION_ERROR",
  "timestamp": "2026-04-22T15:30:45Z"
}
```

#### Complete Message Flow

1. Client connects: `new WebSocket('ws://localhost:8000/ws/chat')`
2. Client sends: `query` message
3. Server sends: one `status` message
4. Server sends: `results` (success) OR `error` (failure)
5. Connection remains open for next query
6. Repeat steps 2-5, OR client calls `ws.close()`

#### Cross-Channel Consistency

**Configuration Awareness:**
- WebSocket queries use the **current configuration** at time of retrieval
- If config changes via `PUT /config` while a query is in-flight, that query uses **old config**
- Next WebSocket query uses the **updated config**
- Configuration changes apply immediately to all channels (REST + WebSocket)

**Retriever Status:**
- If retriever is uninitialized, WebSocket connections remain open
- New query messages receive error: `RETRIEVER_NOT_READY`
- Connection recovers automatically after retriever re-initializes
- No automatic client reconnection needed

#### Client Implementation Examples

**Vanilla JavaScript:**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/chat');

ws.onopen = () => console.log('Connected');

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  
  if (msg.type === 'status') {
    console.log('Status:', msg.message);
  } else if (msg.type === 'results') {
    console.log('Results:', msg.results);
  } else if (msg.type === 'error') {
    console.error('Error:', msg.message);
  }
};

ws.onerror = (error) => console.error('WebSocket error:', error);
ws.onclose = () => console.log('Disconnected');

// Send a query
ws.send(JSON.stringify({
  type: 'query',
  query: 'How do offline maps work?',
  enable_rerank: true
}));
```

**React Hooks:**
```typescript
import { useEffect, useRef, useState } from 'react';

export function useHybridRAG(wsUrl: string) {
  const [status, setStatus] = useState<string>('');
  const [results, setResults] = useState<any[]>([]);
  const [error, setError] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    ws.current = new WebSocket(wsUrl);
    ws.current.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'status') setStatus(msg.message);
      else if (msg.type === 'results') {
        setResults(msg.results);
        setIsLoading(false);
      } else if (msg.type === 'error') {
        setError(msg.message);
        setIsLoading(false);
      }
    };
    
    return () => ws.current?.close();
  }, [wsUrl]);

  const query = (queryText: string) => {
    setIsLoading(true);
    setResults([]);
    ws.current?.send(JSON.stringify({
      type: 'query',
      query: queryText
    }));
  };

  return { query, results, status, error, isLoading };
}
```

#### Connection Management

**Heartbeat (Keep-Alive):**
WebSocket connections may be closed by proxies after inactivity. Implement client-side heartbeat:

```javascript
const heartbeatInterval = setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'ping'}));  // Light keep-alive
  }
}, 30000);  // Every 30 seconds
```

**Automatic Reconnection:**
```javascript
async function connectWithRetry(url, maxAttempts = 3) {
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const ws = new WebSocket(url);
      await new Promise((resolve, reject) => {
        ws.onopen = resolve;
        ws.onerror = reject;
      });
      return ws;
    } catch (error) {
      if (attempt === maxAttempts) throw error;
      // Exponential backoff: 1s, 2s, 4s
      await new Promise(r => setTimeout(r, Math.pow(2, attempt - 1) * 1000));
    }
  }
}
```

#### Validation & Constraints

**Server-side validation:**
- `query` is required in each message
- `query` length: 1-500 characters
- Retriever must be initialized
- One query at a time per connection

**Client-side best practices:**
- Validate query before sending
- Handle all message types: `status`, `results`, `error`
- Implement exponential backoff for reconnection
- Set timeout (e.g., 30s) for retrieval completion
- Echo query in UI for user confirmation

### WebSocket Timeout & Connection Management
- No automatic connection timeout configured. For production:
  - Implement heartbeat mechanism (see above)
  - Set client-side reconnection logic (see above)
  - Monitor connection state in frontend

---

## Testing the API

### Quick Manual Tests

**Health check:**
```bash
curl http://localhost:8000/health
```

**Swagger UI:**
Visit `http://localhost:8000/docs` in a browser to explore and test all endpoints interactively.

**Retrieve documents:**
```bash
curl -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "test query"}'
```

**WebSocket test (bash + websocat):**
```bash
# Install websocat if needed: cargo install websocat
echo '{"query": "offline maps"}' | websocat ws://localhost:8000/ws/chat
```

---

## See Also

- [Library Design](./LIBRARY_DESIGN.md) - Core library architecture
- [Quick Start](./QUICK_START.md) - Using the library programmatically
- [Workspace Instructions](./copilot-instructions.md) - Development conventions
