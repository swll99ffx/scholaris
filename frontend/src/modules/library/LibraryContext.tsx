import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  deleteLibraryItem,
  downloadLibraryExport,
  listLibrary,
  saveToLibrary,
  updateLibraryItem,
} from "../../api/client";
import type { ExportFormat, LibraryItem, Source } from "../../api/types";

// The library (saved sources + RRLs) is shared by the search page and the
// dedicated Library page, so it lives in one provider instead of per-page state.
interface LibraryContextValue {
  items: LibraryItem[];
  savedIds: Set<string>;
  loading: boolean;
  exporting: ExportFormat | null;
  refresh: () => Promise<void>;
  save: (source: Source) => Promise<void>;
  update: (libraryId: string, updates: { notes?: string; tags?: string[] }) => Promise<void>;
  remove: (libraryId: string) => Promise<void>;
  exportAs: (format: ExportFormat) => Promise<void>;
  notify: (message: string) => void;
}

const LibraryContext = createContext<LibraryContextValue | null>(null);

export function LibraryProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => {
      setToast((current) => (current === message ? null : current));
    }, 2600);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listLibrary();
      setItems(
        data.sources.map((item) => ({
          ...item,
          author_details: item.author_details ?? [],
          author_check: item.author_check ?? {
            status: "ok",
            reason: "",
            conflicts: [],
          },
        })),
      );
    } catch {
      // The API being offline should not blank the page; the status dot warns.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const save = useCallback(
    async (source: Source) => {
      try {
        await saveToLibrary(source);
        await refresh();
        notify("Saved to your library");
      } catch (caught) {
        notify(caught instanceof Error ? caught.message : "Could not save that source.");
      }
    },
    [notify, refresh],
  );

  const update = useCallback(
    async (libraryId: string, updates: { notes?: string; tags?: string[] }) => {
      try {
        await updateLibraryItem(libraryId, updates);
        await refresh();
        notify("Library updated");
      } catch (caught) {
        notify(caught instanceof Error ? caught.message : "Could not update that source.");
      }
    },
    [notify, refresh],
  );

  const remove = useCallback(
    async (libraryId: string) => {
      try {
        await deleteLibraryItem(libraryId);
        await refresh();
        notify("Removed from library");
      } catch (caught) {
        notify(caught instanceof Error ? caught.message : "Could not remove that source.");
      }
    },
    [notify, refresh],
  );

  const exportAs = useCallback(
    async (format: ExportFormat) => {
      setExporting(format);
      try {
        await downloadLibraryExport(format);
        notify(`Exported as ${format.toUpperCase()}`);
      } catch (caught) {
        notify(caught instanceof Error ? caught.message : "Export failed.");
      } finally {
        setExporting(null);
      }
    },
    [notify],
  );

  const value = useMemo<LibraryContextValue>(
    () => ({
      items,
      savedIds: new Set(items.map((item) => item.id)),
      loading,
      exporting,
      refresh,
      save,
      update,
      remove,
      exportAs,
      notify,
    }),
    [items, loading, exporting, refresh, save, update, remove, exportAs, notify],
  );

  return (
    <LibraryContext.Provider value={value}>
      {children}
      {toast ? <div className="toast">{toast}</div> : null}
    </LibraryContext.Provider>
  );
}

export function useLibrary(): LibraryContextValue {
  const context = useContext(LibraryContext);
  if (!context) {
    throw new Error("useLibrary must be used inside <LibraryProvider>");
  }
  return context;
}
