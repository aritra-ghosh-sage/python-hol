import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { SettingsPanel } from "./SettingsPanel";
import { apiClient } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiClient: {
    getConfig: vi.fn(),
    getCollections: vi.fn(),
    healthCheck: vi.fn(),
    updateConfig: vi.fn(),
  },
}));

const baseConfig = {
  semantic_top_k: 5,
  keyword_top_k: 5,
  final_top_k: 5,
  semantic_weight: 0.7,
  keyword_weight: 0.3,
  enable_rerank: false,
  pre_rerank_top_k: 20,
  collection_name: "hybrid_rag_collection",
};

function setupMocks() {
  vi.mocked(apiClient.getConfig).mockResolvedValue(baseConfig);
  vi.mocked(apiClient.getCollections).mockResolvedValue({
    collections: [
      { name: "hybrid_rag_collection", count: 42 },
      { name: "other_collection", count: 7 },
    ],
  });
  vi.mocked(apiClient.healthCheck).mockResolvedValue({
    status: "ok",
    retriever_ready: "yes",
  });
}

describe("SettingsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders_active_collection_dropdown", async () => {
    setupMocks();

    render(<SettingsPanel />);

    await waitFor(() => {
      expect(screen.getByLabelText("Active Collection")).toBeDefined();
    });
  });

  it("validates_new_collection_name_input", async () => {
    setupMocks();

    render(<SettingsPanel />);

    // Wait for the component to finish loading
    await waitFor(() => {
      expect(screen.getByLabelText("New Collection Name")).toBeDefined();
    });

    const input = screen.getByLabelText("New Collection Name");
    fireEvent.change(input, { target: { value: "ab" } });

    // Validation message should appear for invalid (too short) input
    await waitFor(() => {
      expect(
        screen.getByText(
          "Must be 6–20 characters, alphanumeric, underscore, or hyphen only"
        )
      ).toBeDefined();
    });

    // "Create & Switch" button should be disabled
    const button = screen.getByRole("button", { name: /create and switch/i });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("accepts_valid_collection_name", async () => {
    setupMocks();

    render(<SettingsPanel />);

    // Wait for the component to finish loading
    await waitFor(() => {
      expect(screen.getByLabelText("New Collection Name")).toBeDefined();
    });

    const input = screen.getByLabelText("New Collection Name");
    fireEvent.change(input, { target: { value: "valid_col" } });

    // No validation message should be visible
    expect(
      screen.queryByText(
        "Must be 6–20 characters, alphanumeric, underscore, or hyphen only"
      )
    ).toBeNull();

    // "Create & Switch" button should be enabled
    const button = screen.getByRole("button", { name: /create and switch/i });
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });
});
