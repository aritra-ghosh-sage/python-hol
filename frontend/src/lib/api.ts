/**
 * REST API client for non-WebSocket endpoints
 */

import {
  CollectionsResponse,
  ConfigResponse,
  ConfigUpdateRequest,
  DocumentIngestionRequest,
  DocumentIngestionResponse,
  HealthResponse,
  SourcesResponse,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_URL) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(
    endpoint: string,
    options?: RequestInit
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(
        error.detail || `API error: ${response.statusText}`
      );
    }

    return response.json();
  }

  async healthCheck(): Promise<HealthResponse> {
    return this.request<HealthResponse>("/health");
  }

  async getConfig(): Promise<ConfigResponse> {
    return this.request<ConfigResponse>("/config");
  }

  async updateConfig(request: ConfigUpdateRequest): Promise<ConfigResponse> {
    return this.request<ConfigResponse>("/config", {
      method: "PUT",
      body: JSON.stringify(request),
    });
  }

  async addDocuments(
    request: DocumentIngestionRequest
  ): Promise<DocumentIngestionResponse> {
    return this.request<DocumentIngestionResponse>("/documents", {
      method: "POST",
      body: JSON.stringify(request),
    });
  }

  async getDocumentSources(): Promise<SourcesResponse> {
    return this.request<SourcesResponse>("/documents/sources");
  }

  async getCollections(): Promise<CollectionsResponse> {
    return this.request<CollectionsResponse>("/collections");
  }
}

export const apiClient = new ApiClient();
