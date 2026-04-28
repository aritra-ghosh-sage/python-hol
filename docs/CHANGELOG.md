# Changelog

All notable changes to the Hybrid RAG project are documented in this file. This includes
the `hybrid_rag/` library, the `api.py` FastAPI service, and the `frontend/` Next.js
application. Changes are grouped by approximate date band and categorized following the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) convention.

---

## [Unreleased] — 2026-04-28

### Fixed

- `initialize_retriever()` in `api.py` was unconditionally calling `initialize_vector_db()`
  on every process start, silently overwriting persisted ChromaDB data. It now calls
  `list_existing_collections()` first; existing collections are opened with
  `open_collection()` and sample documents are seeded only when the collection is absent.
  New coverage in `tests/test_initialize_retriever_startup.py`. (3dad77e)

### Chore

- Removed agent plan artifacts from the repository; added `docs/plan/` to `.gitignore`
  so generated planner output is never committed. (948dc77)

---

## 2026-04-27

### Added

- End-to-end tests for the Settings panel. (PR #63, be84dcd)

### Changed

- Standardized the default collection name to `"rag_collection"` across all files;
  previously some paths defaulted to `"hybrid_rag_collection"`. (88ab0bb)
- Refactored `SettingsPanel` to derive state from the centralized `settingsStore` instead
  of component-local state. (98ade31)
- Removed the `CollectionsResponse` type and simplified `DocumentIngestionRequest`;
  cleaned up imports in `hybrid_rag/__init__.py` and updated `__all__`. (2b20ccf)
- Updated Python and frontend dependencies. (2b20ccf)

### Fixed

- Added E2E test scripts to the ESLint ignore list to suppress spurious lint errors.
  (9372a79)
- Applied review feedback: moved embed model reference to a named constant, switched to
  portable path handling, used `tmp_path` pytest fixture, and fixed empty-settings
  handling. (47056e8)

---

## 2026-04-27 (PR #64–#65 — embedding logic and collections)

### Added

- `settings.json` file-permission handling in the settings panel. (e1a6cd4)

### Changed

- Refactored collections handling in the settings panel to use the `CollectionInfo` type
  consistently. (e1a6cd4)

### Fixed

- Moved `import re` to module level in `vectordb.py`; prevents collection data loss when
  switching between collections. (317fb40)
- Fixed cache integration test to include `collection_name` in `updated_config`, aligning
  the test with the actual config schema. (300b925)
- Updated `lucide-react` to v1.11.0. (28e2471)
- Added `chroma.sqlite3` and `frontend/tmp-e2e/screenshots` to `.gitignore`. (c068c63)

---

## Earlier 2026

### Added

- Multi-collection support: `is_valid_collection_name()`, `sanitize_collection_name()`,
  and `list_existing_collections()` utility functions in `hybrid_rag/vectordb.py`.
  ChromaDB enforces 6–20 character collection names; these utilities validate and coerce
  names accordingly.
- `collection_name` field on `HybridRetrieverConfig` (default: `"rag_collection"`).
- `GET /collections` REST endpoint for listing available ChromaDB collections.
- Chat history persistence via Zustand + `localStorage`, capped at `MAX_CHAT_HISTORY`
  (200 messages).
- L2 embedding LRU cache inside `HybridRetriever` (5000-entry maximum), reducing redundant
  embedding calls within a session.
- Corpus version token (`_corpus_version`) for L1 cache keying, derived from
  `_cache_generation` combined with a live `collection.count()` read. Incrementing
  `_cache_generation` busts the L1 cache after ingestion or config changes.

### Changed

- Renamed constant `PERSIST_DIRECTORY` to `KNOWLEDGE_DB_DIRECTORY`.
- Migrated the L1 full-response cache to the WebSocket path exclusively (`WS /ws/chat`);
  the `POST /retrieve` endpoint was removed.
- Modernized type hints across the codebase: `List[T]` → `list[T]`,
  `Dict[K, V]` → `dict[K, V]`. (PR #52)
- Added comprehensive Python and TypeScript coding standards to `CLAUDE.md`. (PR #51)

### Fixed

- URL validation and hyperlink rendering in the frontend chat component.
- Test isolation: `_cache_generation` is reset between tests to prevent cross-test cache
  contamination.
- `/collections` endpoint now reads the public `collection` attribute rather than an
  internal reference. (9cc75a1)
