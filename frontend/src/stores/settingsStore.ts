import { create } from "zustand";
import { persist } from "zustand/middleware";
import { CollectionInfo } from "@/lib/types";

export const STALE_THRESHOLD = 15;

interface SettingsState {
  knownCollections: CollectionInfo[];
  mergeCollections: (fresh: CollectionInfo[]) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      knownCollections: [],
      mergeCollections: (fresh: CollectionInfo[]) => {
        const byName = new Map(fresh.map((c) => [c.name, { ...c, missCount: 0 }]));
        for (const known of get().knownCollections) {
          if (!byName.has(known.name)) {
            byName.set(known.name, {
              ...known,
              missCount: (known.missCount ?? 0) + 1,
            });
          }
        }
        set({ knownCollections: Array.from(byName.values()) });
      },
    }),
    {
      name: "settings-store",
      partialize: (state) => ({ knownCollections: state.knownCollections }),
    }
  )
);
