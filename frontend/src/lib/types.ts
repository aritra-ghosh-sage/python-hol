/**
 * TypeScript types matching FastAPI Pydantic models
 */

export interface DocumentResult {
  id: string;
  text: string;
  source: string;
  /** Original URL when source has a custom label */
  source_url?: string;
  /** Relevance score (0-1). After backend filtering, only scores >= 0.85 are shown. */
  score: number;
}

export interface RetrievalRequest {
  query: string;
  enable_rerank?: boolean;
}

export interface RetrievalResponse {
  query: string;
  results: DocumentResult[];
  total_results: number;
}

export interface ConfigResponse {
  semantic_top_k: number;
  keyword_top_k: number;
  final_top_k: number;
  semantic_weight: number;
  keyword_weight: number;
  enable_rerank: boolean;
  pre_rerank_top_k: number;
}

export interface ConfigUpdateRequest {
  semantic_top_k?: number;
  keyword_top_k?: number;
  final_top_k?: number;
  semantic_weight?: number;
  keyword_weight?: number;
  enable_rerank?: boolean;
  pre_rerank_top_k?: number;
}

export interface DocumentIngestionRequest {
  source_type: "text" | "url" | "file";
  content: string; // text, URL, or base64
  filename?: string;
  source_label?: string;
}

export interface DocumentIngestionResponse {
  status: string;
  documents_added: number;
  chunks_created: number;
  message?: string;
}

export interface DocumentSource {
  source: string;
  count: number;
}

export interface SourcesResponse {
  sources: DocumentSource[];
}

export interface HealthResponse {
  status: string;
  retriever_ready: string;
}

// WebSocket message types
export interface WsStatusMessage {
  type: "status";
  message: string;
}

export interface WsResultsMessage {
  type: "results";
  query: string;
  results: DocumentResult[];
  total_results: number;
}

export interface WsErrorMessage {
  type: "error";
  message: string;
}

export type WsIncomingMessage = WsStatusMessage | WsResultsMessage | WsErrorMessage;

export interface WsOutgoingMessage {
  query: string;
  enable_rerank?: boolean;
}

// Chat message type for UI
export interface ChatMessage {
  id: string;
  role: "user" | "system";
  content?: string;
  results?: DocumentResult[];
  timestamp: number;
  status: "sent" | "loading" | "done" | "error";
  error?: string;
}
