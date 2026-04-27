import { create } from "zustand";
import { CollectionInfo } from "@/lib/types";

interface SettingsState {
  knownCollections: CollectionInfo[];
  mergeCollections: (fresh: CollectionInfo[]) => void;
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  knownCollections: [],
  mergeCollections: (fresh) => {
    const byName = new Map(fresh.map((c) => [c.name, c]));
    for (const known of get().knownCollections) {
      if (!byName.has(known.name)) {
        byName.set(known.name, known);
      }
    }
    set({ knownCollections: Array.from(byName.values()) });
  },
}));
