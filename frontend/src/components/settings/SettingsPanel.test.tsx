import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { SettingsPanel } from "./SettingsPanel";
import { apiClient } from "@/lib/api";
import { useSettingsStore, STALE_THRESHOLD } from "@/stores/settingsStore";

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
  collection_name: "rag_collection",
};

function setupMocks() {
  vi.mocked(apiClient.getConfig).mockResolvedValue(baseConfig);
  vi.mocked(apiClient.getCollections).mockResolvedValue({
    collections: [
      { name: "rag_collection", count: 42 },
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
    useSettingsStore.setState({ knownCollections: [] });
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

describe("mergeCollections staleness", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({ knownCollections: [] });
  });

  afterEach(() => {
    cleanup();
  });

  it("increments_missCount_for_absent_collection", () => {
    const { mergeCollections } = useSettingsStore.getState();

    // First merge: collection 'a' is present
    mergeCollections([{ name: "a", count: 1 }]);

    // Second merge: only 'b' is present; 'a' is absent
    mergeCollections([{ name: "b", count: 2 }]);

    const { knownCollections } = useSettingsStore.getState();
    const collectionA = knownCollections.find((c) => c.name === "a");
    expect(collectionA).toBeDefined();
    expect(collectionA?.missCount).toBe(1);
  });

  it("hides_stale_collection_from_dropdown", async () => {
    // Seed store with a nearly-stale collection
    useSettingsStore.setState({
      knownCollections: [{ name: "stale", count: 0, missCount: STALE_THRESHOLD - 1 }],
    });

    // Setup mocks: fresh list only has 'active', not 'stale'
    vi.mocked(apiClient.getConfig).mockResolvedValue({
      ...baseConfig,
      collection_name: "active_col",
    });
    vi.mocked(apiClient.getCollections).mockResolvedValue({
      collections: [{ name: "active_col", count: 5 }],
    });
    vi.mocked(apiClient.healthCheck).mockResolvedValue({
      status: "ok",
      retriever_ready: "yes",
    });

    render(<SettingsPanel />);

    // Wait for loading to complete
    await waitFor(() => {
      expect(screen.getByLabelText("Active Collection")).toBeDefined();
    });

    // After mergeCollections is called, 'stale' missCount becomes STALE_THRESHOLD
    // so it should not appear in the dropdown
    const dropdown = screen.getByLabelText("Active Collection");
    const options = Array.from((dropdown as HTMLSelectElement).options).map(
      (o) => o.value
    );
    expect(options).not.toContain("stale");
  });

  it("resets_missCount_when_collection_reappears", () => {
    // Seed with a gone collection that was very stale
    useSettingsStore.setState({
      knownCollections: [{ name: "gone", count: 0, missCount: STALE_THRESHOLD + 2 }],
    });

    const { mergeCollections } = useSettingsStore.getState();

    // 'gone' reappears in the fresh list
    mergeCollections([{ name: "gone", count: 10 }]);

    const { knownCollections } = useSettingsStore.getState();
    const goneCol = knownCollections.find((c) => c.name === "gone");
    expect(goneCol).toBeDefined();
    expect(goneCol?.missCount).toBe(0);
    expect(goneCol?.count).toBe(10);
  });

  it("blocks_save_when_collection_name_is_stale", async () => {
    // Seed store with a stale 'deleted' collection
    useSettingsStore.setState({
      knownCollections: [{ name: "deleted", count: 0, missCount: STALE_THRESHOLD }],
    });

    vi.mocked(apiClient.getConfig).mockResolvedValue({
      ...baseConfig,
      collection_name: "deleted",
    });
    vi.mocked(apiClient.getCollections).mockResolvedValue({
      collections: [],
    });
    vi.mocked(apiClient.healthCheck).mockResolvedValue({
      status: "ok",
      retriever_ready: "yes",
    });

    render(<SettingsPanel />);

    // Wait for the component to finish loading
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /save settings/i })).toBeDefined();
    });

    // Click Save Settings
    const saveButton = screen.getByRole("button", { name: /save settings/i });
    fireEvent.click(saveButton);

    // updateConfig should NOT have been called
    expect(vi.mocked(apiClient.updateConfig)).not.toHaveBeenCalled();

    // An error message containing "no longer available" should be shown
    await waitFor(() => {
      expect(screen.getByText(/no longer available/i)).toBeDefined();
    });
  });
});
