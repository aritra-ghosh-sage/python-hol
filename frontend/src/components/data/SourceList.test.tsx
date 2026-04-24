import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SourceList } from "./SourceList";
import { apiClient } from "@/lib/api";
import type { DocumentSource } from "@/lib/types";

// Mock the API client
vi.mock("@/lib/api", () => ({
  apiClient: {
    getDocumentSources: vi.fn(),
  },
}));

describe("SourceList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("should show loading state initially", () => {
    vi.mocked(apiClient.getDocumentSources).mockImplementation(
      () => new Promise(() => {}) // Never resolves
    );

    render(<SourceList />);
    // Shimmer component should be rendered during loading
    expect(document.querySelector(".animate-pulse")).toBeTruthy();
  });

  it("should display 'No sources ingested yet' when there are no sources", async () => {
    vi.mocked(apiClient.getDocumentSources).mockResolvedValue({
      sources: [],
    });

    render(<SourceList />);

    await waitFor(() => {
      expect(screen.getByText("No sources ingested yet")).toBeDefined();
    });
  });

  it("should display singular source and chunk count", async () => {
    const mockSources: DocumentSource[] = [
      { source: "Test Document", count: 1 },
    ];

    vi.mocked(apiClient.getDocumentSources).mockResolvedValue({
      sources: mockSources,
    });

    render(<SourceList />);

    await waitFor(() => {
      expect(screen.getByText("1 source (1 chunk)")).toBeDefined();
    });
  });

  it("should display plural sources and chunks count", async () => {
    const mockSources: DocumentSource[] = [
      { source: "Document 1", count: 5 },
      { source: "Document 2", count: 3 },
      { source: "Document 3", count: 2 },
    ];

    vi.mocked(apiClient.getDocumentSources).mockResolvedValue({
      sources: mockSources,
    });

    render(<SourceList />);

    await waitFor(() => {
      // 3 sources, total 10 chunks (5 + 3 + 2)
      expect(screen.getByText("3 sources (10 chunks)")).toBeDefined();
    });
  });

  it("should handle mixed singular/plural correctly (multiple sources, single total chunk)", async () => {
    const mockSources: DocumentSource[] = [
      { source: "Document 1", count: 1 },
    ];

    vi.mocked(apiClient.getDocumentSources).mockResolvedValue({
      sources: mockSources,
    });

    render(<SourceList />);

    await waitFor(() => {
      expect(screen.getByText("1 source (1 chunk)")).toBeDefined();
    });
  });

  it("should display error message when API call fails", async () => {
    const errorMessage = "Failed to load sources";
    vi.mocked(apiClient.getDocumentSources).mockRejectedValue(
      new Error(errorMessage)
    );

    render(<SourceList />);

    await waitFor(() => {
      expect(screen.getByText(errorMessage)).toBeDefined();
    });
  });

  it("should refresh sources when refreshTrigger changes", async () => {
    const initialSources: DocumentSource[] = [
      { source: "Document 1", count: 5 },
    ];

    const updatedSources: DocumentSource[] = [
      { source: "Document 1", count: 5 },
      { source: "Document 2", count: 3 },
    ];

    vi.mocked(apiClient.getDocumentSources)
      .mockResolvedValueOnce({ sources: initialSources })
      .mockResolvedValueOnce({ sources: updatedSources });

    const { rerender } = render(<SourceList refreshTrigger={0} />);

    await waitFor(() => {
      expect(screen.getByText("1 source (5 chunks)")).toBeDefined();
    });

    // Trigger refresh
    rerender(<SourceList refreshTrigger={1} />);

    await waitFor(() => {
      expect(screen.getByText("2 sources (8 chunks)")).toBeDefined();
    });

    expect(apiClient.getDocumentSources).toHaveBeenCalledTimes(2);
  });

  it("should clear error state on successful retry", async () => {
    vi.mocked(apiClient.getDocumentSources)
      .mockRejectedValueOnce(new Error("Network error"))
      .mockResolvedValueOnce({
        sources: [{ source: "Document 1", count: 3 }],
      });

    const { rerender } = render(<SourceList refreshTrigger={0} />);

    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeDefined();
    });

    // Trigger refresh
    rerender(<SourceList refreshTrigger={1} />);

    await waitFor(() => {
      expect(screen.getByText("1 source (3 chunks)")).toBeDefined();
    });

    // Error should be cleared
    expect(screen.queryByText("Network error")).toBeNull();
  });

  it("should calculate total chunks correctly across multiple sources", async () => {
    const mockSources: DocumentSource[] = [
      { source: "Doc A", count: 10 },
      { source: "Doc B", count: 15 },
      { source: "Doc C", count: 5 },
      { source: "Doc D", count: 20 },
    ];

    vi.mocked(apiClient.getDocumentSources).mockResolvedValue({
      sources: mockSources,
    });

    render(<SourceList />);

    await waitFor(() => {
      // 4 sources, total 50 chunks (10 + 15 + 5 + 20)
      expect(screen.getByText("4 sources (50 chunks)")).toBeDefined();
    });
  });
});
