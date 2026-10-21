import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { fetchNotes, searchSources } from "../../api/client";
import type { SearchFilters, SearchResponse, SortMode, Source } from "../../api/types";

// Module 1's search lives here (not in ResearchPage) so navigating to the
// Library and back does not wipe your results. It is also mirrored into
// sessionStorage so a refresh keeps the last search.
const STORAGE_KEY = "scholaris:research";
const RECENT_KEY = "scholaris:recent-searches";

// The feed is a UI detail: 20 results render at first, then 20 more at a time
// as you scroll. The cap is intentionally not exposed in the search card.
export const RESULT_FEED_LIMIT = 100;
export const RESULT_PAGE_SIZE = 20;
const MAX_RECENT_SEARCHES = 5;

export const DEFAULT_FILTERS: SearchFilters = {
  year_from: null,
  year_to: null,
  reviews_only: false,
  open_access_only: false,
  english_only: true,
  subject: "any",
  relevance_mode: "strict",
  limit: RESULT_FEED_LIMIT,
  deep_search: false,
  exclude_preprints: false,
};

function loadRecentSearches(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is string => typeof item === "string")
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, MAX_RECENT_SEARCHES);
  } catch {
    return [];
  }
}

function saveRecentSearches(items: string[]): void {
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(items));
  } catch {
    // Private mode / quota: recents are a convenience, never a hard fail.
  }
}

interface PersistedState {
  query: string;
  filters: SearchFilters;
  sort: SortMode;
  result: SearchResponse | null;
}

function normalizeResult(result: SearchResponse | null): SearchResponse | null {
  if (!result) return null;
  // Results cached before a field was added must not crash the page.
  return {
    ...result,
    concepts: result.concepts ?? [],
    sources: (result.sources ?? []).map((source) => ({
      ...source,
      author_details: source.author_details ?? [],
      author_check: source.author_check ?? { status: "ok", reason: "", conflicts: [] },
      article_number: source.article_number ?? null,
      is_administrative: source.is_administrative ?? false,
      is_retracted: source.is_retracted ?? false,
      is_preprint: source.is_preprint ?? false,
      is_non_primary: source.is_non_primary ?? false,
      score_breakdown: source.score_breakdown ?? {},
    })),
  };
}

function loadState(): PersistedState {
  const fallback: PersistedState = {
    query: "",
    filters: DEFAULT_FILTERS,
    sort: "match",
    result: null,
  };
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<PersistedState>;
    return {
      query: typeof parsed.query === "string" ? parsed.query : "",
      // Older sessions stored a visible max-sources value. The feed is now
      // always filled up to its hidden cap.
      filters: {
        ...DEFAULT_FILTERS,
        ...(parsed.filters ?? {}),
        limit: RESULT_FEED_LIMIT,
      },
      sort: parsed.sort ?? "match",
      result: normalizeResult(parsed.result ?? null),
    };
  } catch {
    return fallback;
  }
}

interface ResearchContextValue {
  query: string;
  setQuery: (value: string) => void;
  filters: SearchFilters;
  setFilters: (filters: SearchFilters) => void;
  resetFilters: () => void;
  sort: SortMode;
  setSort: (mode: SortMode) => void;
  result: SearchResponse | null;
  searchVersion: number;
  loading: boolean;
  error: string | null;
  relatedSource: Source | null;
  setRelatedSource: (source: Source | null) => void;
  recentSearches: string[];
  clearRecentSearches: () => void;
  runSearch: (queryOverride?: string, filtersOverride?: SearchFilters) => Promise<void>;
}

const ResearchContext = createContext<ResearchContextValue | null>(null);

export function ResearchProvider({ children }: { children: ReactNode }) {
  const [initial] = useState<PersistedState>(loadState);
  const [query, setQuery] = useState(initial.query);
  const [filters, setFilters] = useState<SearchFilters>(initial.filters);
  const [sort, setSort] = useState<SortMode>(initial.sort);
  const [result, setResult] = useState<SearchResponse | null>(initial.result);
  // Increments only after a completed search, so the page can reset its
  // progressive feed without collapsing when background notes update.
  const [searchVersion, setSearchVersion] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [relatedSource, setRelatedSource] = useState<Source | null>(null);
  const [recentSearches, setRecentSearches] = useState<string[]>(loadRecentSearches);
  // A stale response must never overwrite a newer search. Each run gets an ID
  // and an AbortController; starting another search cancels the old request and
  // its background note upgrade.
  const runIdRef = useRef(0);
  const activeSearchRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => activeSearchRef.current?.abort();
  }, []);

  useEffect(() => {
    try {
      const state: PersistedState = { query, filters, sort, result };
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // Private mode / quota: persistence is a nice-to-have, never a hard fail.
    }
  }, [query, filters, sort, result]);

  const runSearch = useCallback(
    async (queryOverride?: string, filtersOverride?: SearchFilters) => {
      const effectiveQuery = (queryOverride ?? query).trim();
      const effectiveFilters = filtersOverride ?? filters;
      if (effectiveQuery.length < 2) return;

      // Chip clicks can start a search before React has committed the new
      // query/filter state. Use the caller's values for this request and keep
      // the visible controls in sync.
      if (queryOverride !== undefined) setQuery(effectiveQuery);
      if (filtersOverride !== undefined) setFilters(filtersOverride);

      activeSearchRef.current?.abort();
      const controller = new AbortController();
      activeSearchRef.current = controller;
      const runId = ++runIdRef.current;
      let timedOut = false;
      const timeout = window.setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, 30_000);

      setLoading(true);
      setError(null);
      try {
        const data = await searchSources(effectiveQuery, effectiveFilters, controller.signal);
        if (runId !== runIdRef.current) return;
        setResult(data);
        setSearchVersion((value) => value + 1);

        // Recents are private to this browser and only remember searches that
        // actually produced sources. Prefer the interpreted topic so a pasted
        // assignment brief does not fill the row with a wall of text.
        if (data.sources.length > 0) {
          const label = (data.topic || data.query || effectiveQuery).trim().slice(0, 120);
          if (label) {
            setRecentSearches((current) => {
              const next = [
                label,
                ...current.filter((item) => item.toLowerCase() !== label.toLowerCase()),
              ].slice(0, MAX_RECENT_SEARCHES);
              saveRecentSearches(next);
              return next;
            });
          }
        }

        // Notes are deliberately lazy: cards render immediately with heuristic
        // notes, then the top few are upgraded in the background.
        const noteTargets = data.sources.slice(0, 3);
        if (noteTargets.length > 0) {
          void fetchNotes(data.topic || data.query, noteTargets, controller.signal)
            .then((response) => {
              if (runId !== runIdRef.current || response.notes.length === 0) return;
              const byId = new Map(response.notes.map((note) => [note.id, note]));
              setResult((current) => {
                if (!current) return current;
                return {
                  ...current,
                  sources: current.sources.map((source) => {
                    const note = byId.get(source.id);
                    return note
                      ? { ...source, ai_note: note.note, ai_note_source: note.source }
                      : source;
                  }),
                };
              });
            })
            .catch(() => {
              // A failed note upgrade leaves the useful heuristic note in place.
            });
        }
      } catch (caught) {
        if (runId !== runIdRef.current) return;
        if (timedOut) {
          setError("The search took too long. Check your internet connection and try again.");
        } else if (!controller.signal.aborted) {
          const message = caught instanceof Error ? caught.message.trim() : "";
          if (
            !message ||
            /failed to fetch|load failed|networkerror|network request failed/i.test(message)
          ) {
            setError("I couldn't reach the search service. Check your connection and try again.");
          } else {
            setError(message);
          }
        }
      } finally {
        window.clearTimeout(timeout);
        if (runId === runIdRef.current) setLoading(false);
      }
    },
    [query, filters],
  );

  const clearRecentSearches = useCallback(() => {
    setRecentSearches([]);
    saveRecentSearches([]);
  }, []);

  const resetFilters = useCallback(() => {
    // Relevance and Deep search sit outside the Filters panel, so resetting
    // filters must not silently change them.
    setFilters((current) => ({
      ...DEFAULT_FILTERS,
      relevance_mode: current.relevance_mode,
      deep_search: current.deep_search,
    }));
  }, []);

  const value = useMemo<ResearchContextValue>(
    () => ({
      query,
      setQuery,
      filters,
      setFilters,
      resetFilters,
      sort,
      setSort,
      result,
      searchVersion,
      loading,
      error,
      relatedSource,
      setRelatedSource,
      recentSearches,
      clearRecentSearches,
      runSearch,
    }),
    [
      query,
      filters,
      resetFilters,
      sort,
      result,
      searchVersion,
      loading,
      error,
      relatedSource,
      recentSearches,
      clearRecentSearches,
      runSearch,
    ],
  );

  return <ResearchContext.Provider value={value}>{children}</ResearchContext.Provider>;
}

export function useResearch(): ResearchContextValue {
  const context = useContext(ResearchContext);
  if (!context) {
    throw new Error("useResearch must be used inside <ResearchProvider>");
  }
  return context;
}
