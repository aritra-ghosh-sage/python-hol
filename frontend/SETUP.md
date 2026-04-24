# Hybrid RAG - Complete Setup & Usage Guide

## 🎉 Project Complete!

Your full-stack Hybrid RAG application is ready to deploy. This guide covers setup, running, and features.

---

## 📋 Project Structure

```
python-hol/
├─ api.py                           # FastAPI backend (WebSocket + REST endpoints)
├─ hybrid_rag/                       # Core RAG library
├─ pyproject.toml                    # Python dependencies (added pypdf)
└─ frontend/                         # Next.js frontend
   ├─ public/                        # Static assets
   ├─ src/
   │  ├─ app/                        # Next.js app router
   │  ├─ components/                 # React components (15 total)
   │  ├─ lib/                        # API/WebSocket clients + types
   │  ├─ hooks/                      # useChat, useApi
   │  └─ globals.css                 # Tailwind + custom styles
   └─ package.json
```

---

## 🚀 Quick Start

### 1. Backend Setup (Python)

```bash
cd /home/aritraghosh/projects/python-hol

# Activate virtual environment
source .venv/bin/activate

# Install new dependencies (pypdf)
pip install pypdf requests

# Run FastAPI server
python api.py
# Output: Swagger UI: http://localhost:8000/docs
#         WebSocket Chat: ws://localhost:8000/ws/chat
```

### 2. Frontend Setup (Node.js)

```bash
cd /home/aritraghosh/projects/python-hol/frontend

# Install dependencies (already done, but if needed:)
# pnpm install

# Development mode (live reload)
pnpm dev
# Output: ▲ Next.js on http://localhost:3000

# Production build
pnpm build
pnpm start  # Runs optimized production build
```

### 3. Access the Application

- **Frontend**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

---

## ✨ Features Implemented

### Backend (FastAPI)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ws/chat` | WebSocket | Real-time query/response with status updates (primary retrieval path) |
| `/documents` | POST | Add custom data (text/URL/files) |
| `/documents/sources` | GET | List ingested document sources |
| `/config` | GET/PUT | View/update retriever settings |
| `/health` | GET | Health check endpoint |

**CORS Enabled**: Frontend on `:3000` can call backend on `:8000`

### Frontend (Next.js)

#### Main Panels (Navigation)

1. **Query Panel** (default)
   - WebSocket-based real-time chat
   - Connection status indicator
   - Auto-scrolling message history
   - Document results with scores and sources
   - 100-word limit on queries

2. **Add Data Panel**
   - **Text Tab**: Paste raw text/documentation
   - **URL Tab**: Add web content by URL
   - **File Tab**: Upload `.txt`, `.md`, `.pdf` files (with drag-and-drop)
   - Source list showing ingested documents

3. **Settings Panel**
   - View/edit retriever configuration
   - Semantic & keyword Top-K sliders
   - Score weight adjustment (auto-balances)
   - Reranking toggle & pre-rerank settings
   - Service health status indicator

#### UI/UX Features

- **Shimmer loaders**: Animated placeholders while fetching
- **Toast messages**: Success/error notifications
- **Keyboard shortcuts**: Enter to send, Shift+Enter for newline, Escape to clear
- **Responsive design**: Sidebar collapses on mobile
- **Dark theme**: Professional dark UI with blue accent
- **Fonts**: Inter (body) + JetBrains Mono (code/scores) from Google Fonts

---

## 🔌 WebSocket Protocol

### Client → Server

```json
{
  "query": "How do I use offline maps?",
  "enable_rerank": true
}
```

### Server → Client (sequence)

1. **Status message**:
   ```json
   { "type": "status", "message": "Retrieving documents..." }
   ```

2. **Results message**:
   ```json
   {
     "type": "results",
     "query": "How do I use offline maps?",
     "results": [
       {
         "id": "doc-1",
         "text": "To use offline maps...",
         "source": "https://example.com/maps",
         "score": 0.92
       }
     ],
     "total_results": 1
   }
   ```

3. **Error message** (on failure):
   ```json
   { "type": "error", "message": "Retrieval failed" }
   ```

### Auto-Reconnect

- Exponential backoff: 1s → 2s → 4s
- Max 3 retries
- Connection state displayed in UI

---

## 🛠️ Configuration

### Environment Variables

**Frontend** (`.env.local` in `frontend/`):

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/chat
```

**Backend** (set via environment before running):

```bash
# Customize CORS origins (comma-separated)
export CORS_ORIGINS="http://localhost:3000,http://localhost:3001"

python api.py
```

### Retriever Configuration (Editable in Settings)

- **semantic_top_k** (1-20): Semantic search results count
- **keyword_top_k** (1-20): Keyword search results count
- **final_top_k** (1-20): Maximum final results
- **semantic_weight** (0-1): Semantic search weight
- **keyword_weight** (0-1): Keyword search weight (auto-balances)
- **enable_rerank** (bool): Use cross-encoder reranking
- **pre_rerank_top_k** (10-100): Candidates to rerank

---

## 📦 Dependencies

### Backend

```toml
fastapi>=0.135.3      # Web framework
uvicorn>=0.44.0       # ASGI server
pydantic>=2.12.5      # Data validation
pypdf>=4.0.0          # PDF text extraction (NEW)
requests>=2.33.1      # HTTP client
chromadb>=1.5.7       # Vector DB
sentence-transformers>=5.3.0  # Embeddings & reranking
# ... (see pyproject.toml for full list)
```

### Frontend

```json
{
  "next": "16.2.3",
  "react": "19.2.4",
  "lucide-react": "1.8.0",      // Icons
  "tailwindcss": "4.2.2",
  "typescript": "5.9.3"
}
```

---

## 🧪 Testing Workflows

### 1. Query Flow

```bash
# Terminal 1: Start backend
cd /home/aritraghosh/projects/python-hol
source .venv/bin/activate
python api.py

# Terminal 2: Start frontend
cd /home/aritraghosh/projects/python-hol/frontend
pnpm dev

# Browser: Navigate to http://localhost:3000
# → Type a question → See results from vector DB
```

### 2. Add Custom Data

1. Go to "Add Data" panel
2. **Text**: Paste FAQ content → submit → query it
3. **URL**: Enter https://example.com → fetch & ingest
4. **File**: Drag PDF/TXT → upload → search contents
5. Check "Ingested Sources" to verify

### 3. Settings Adjustment

1. Go to "Settings" panel
2. Adjust semantic weight left/right slider
3. Change Top-K values for more/fewer results
4. Toggle reranking on/off → "Save Settings"
5. Query again to see changes

### 4. WebSocket Direct Test (curl)

```bash
# Test WebSocket endpoint
curl --include \
     --no-buffer \
     --header "Upgrade: websocket" \
     --header "Connection: Upgrade" \
     --header "Sec-WebSocket-Key: SGVsbG8sIHdvcmxkIQ==" \
     --header "Sec-WebSocket-Version: 13" \
     http://localhost:8000/ws/chat

# Or use wscat (npm install -g wscat):
wscat -c ws://localhost:8000/ws/chat
> {"query": "What is Hybrid RAG?"}
```

---

## 🚨 Troubleshooting

| Issue | Solution |
|-------|----------|
| `CORS error in browser console` | Backend CORS not enabled. Check api.py line with `CORSMiddleware`. Restart backend. |
| `WebSocket connection refused` | Backend not running on `:8000`. Run `python api.py` first. |
| `Retriever not initialized` | Backend startup failed. Check FastAPI logs for vector DB initialization errors. |
| `"No results found"` | Add data first via Add Data panel; sample docs always included at startup. |
| `PDF upload fails` | `pypdf` not installed. Run `pip install pypdf` in venv. |
| `"page.tsx" parsing error` | Template remnants. Already fixed in setup. Run `pnpm dev` again. |

---

## 📊 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                       │
│                    Port 3000 (localhost)                    │
├───────────────────────────────────────────────────────────────┤
│ ┌──────────────────────┐        ┌──────────────────────────┐  │
│ │  Sidebar Navigation  │        │      Main Content Area   │  │
│ │  - Query Panel       │        │ - ChatWindow (WebSocket) │  │
│ │  - Add Data Panel    │───────▶│ - ChatInput              │  │
│ │  - Settings Panel    │        │ - MessageBubble          │  │
│ └──────────────────────┘        │ - AddDataPanel           │  │
│           │                     │ - SettingsPanel          │  │
│           │                     └──────────────────────────┘  │
│           │                                                    │
│           │ REST API + WebSocket                             │
│           │ (CORS enabled)                                   │
│           └─────────────────────────┐                        │
├────────────────────────────────────────────────────────────────┤
│                    Backend (FastAPI)                          │
│                    Port 8000 (localhost)                      │
├────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ /ws/chat (WebSocket)     Handlers for real-time chat   │ │
│ │ /documents (POST)        Add text/URL/files            │ │
│ │ /documents/sources (GET) List ingested sources         │ │
│ │ /config (GET/PUT)        Get/update configuration      │ │
│ │ /health (GET)            Health check                  │ │
│ └──────────────────────────────────────────────────────────┘ │
│                           │                                   │
│                           ▼                                   │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │         Hybrid RAG Retriever (Core Library)             │ │
│ │  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐│ │
│ │  │ Semantic    │  │ Keyword      │  │ Cross-Encoder   ││ │
│ │  │ Search      │─▶│ Search       │─▶│ Reranker        ││ │
│ │  │(Embeddings) │  │(Full-text)   │  │(Optional)       ││ │
│ │  └─────────────┘  └──────────────┘  └─────────────────┘│ │
│ │                                                          │ │
│ │  Score Fusion ──▶ Deduplication ──▶ Final Results    │ │
│ └──────────────────────────────────────────────────────────┘ │
│                           │                                   │
│                           ▼                                   │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │              Vector Database (ChromaDB)                 │ │
│ │  Persistent: ./ai_support_kb/                          │ │
│ │  Embeddings: all-MiniLM-L6-v2 (SentenceTransformers)  │ │
│ │  Always contains: 4 sample Google Maps docs           │ │
│ └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

---

## 🎯 Key Implementation Details

### WebSocket Chat Flow

1. **User types query** → "How do I update maps?"
2. **Frontend sends** JSON via WebSocket: `{ "query": "...", "enable_rerank": true }`
3. **Backend validates** query (1-500 chars)
4. **Backend sends status** message → UI shows shimmer loader
5. **Backend runs hybrid retrieval**:
   - Semantic search (embeddings)
   - Keyword search (full-text)
   - Score fusion (weighted)
   - Optional cross-encoder reranking
   - Deduplication by source
6. **Backend sends results** message with `DocumentResult[]`
7. **Frontend replaces** loader with result cards (source, score, text snippet)

### Document Ingestion

1. **User uploads file** (PDF, TXT, MD) or pastes text
2. **Frontend converts** to base64 → POST to `/documents`
3. **Backend extracts** text:
   - PDF via `pypdf.PdfReader()`
   - Text/MD as-is UTF-8
4. **Backend chunks** text (500 chars, 50 overlap)
5. **Backend adds** to ChromaDB collection with metadata
6. **User can immediately query** the new content

### Configuration Updates

1. **User adjusts weight sliders** in Settings
2. **Frontend validates** that weights sum to 1.0
3. **Frontend sends** `PUT /config` with new values
4. **Backend validates** & updates global `_config`
5. **Subsequent queries** use new configuration
6. **No server restart needed**

---

## 🔐 Security Notes

- **CORS**: Restricted to `localhost:3000/3001` by default (set `CORS_ORIGINS` env var)
- **WebSocket**: No auth; suitable for local/trusted networks
- **File uploads**: Base64 in JSON; validate file size server-side if scaling to production
- **PDF parsing**: Uses `pypdf`; ensure malicious PDFs are filtered

---

## 📈 Performance

- **Frontend**: SSG + streaming (Next.js 16.2)
- **Backend**: Async with uvicorn workers (8 by default)
- **Vector DB**: Local ChromaDB with SentenceTransformer embeddings (CPU-based)
- **Reranking**: Optional; use `enable_rerank: false`config for speed
- **Caching**: API calls always fresh

---

## 🎨 Theming

**Colors** (Tailwind):
- `bg-gray-900/950`: Dark backgrounds
- `bg-blue-500`: Primary actions
- `text-gray-100/300`: Text hierarchy
- Scroll bars: Custom styled

**Typography**:
- Body: Inter from Google Fonts
- Code/Numbers: JetBrains Mono

---

## 📚 Additional Resources

- **FastAPI Docs**: http://localhost:8000/docs (Swagger UI)
- **Next.js Docs**: https://nextjs.org/docs
- **Tailwind Docs**: https://tailwindcss.com/docs
- **ChromaDB Docs**: https://docs.trychroma.com/
- **Hybrid RAG Library**: See `hybrid_rag/__init__.py`

---

## ✅ Checklist for Production

- [ ] Set `CORS_ORIGINS` environment variable to production domains
- [ ] Enable HTTPS (FastAPI behind proxy, Next.js on Vercel/similar)
- [ ] Add authentication (JWT or OAuth)
- [ ] Set up monitoring (logs, metrics)
- [ ] Configure database persistence (ChromaDB already persists)
- [ ] Add rate limiting on `/documents` and `/ws/chat`
- [ ] Test file upload size limits
- [ ] Set up backups for `./ai_support_kb/` directory
- [ ] Deploy frontend (Vercel, Netlify, etc.)
- [ ] Deploy backend (Cloud Run, EC2, Railway, etc.)

---

## 🎉 You're All Set!

Your Hybrid RAG application is complete and ready to use. Start the backend and frontend, then explore:

1. **Ask questions** using the WebSocket chat interface
2. **Add custom knowledge** via text, URLs, or files
3. **Adjust retrieval parameters** in real-time settings

Happy querying! 🚀
