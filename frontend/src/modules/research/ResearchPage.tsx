import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { downloadResultsExport } from "../../api/client";
import type { InputMode, ResultsExportFormat, SortMode, Source } from "../../api/types";
import { Icon } from "../../components/Icon";
import { useLibrary } from "../library/LibraryContext";
import { FriendlyState } from "./FriendlyState";
import { RelatedModal } from "./RelatedModal";
import { DEFAULT_FILTERS, RESULT_PAGE_SIZE, useResearch } from "./ResearchContext";
import { SearchForm } from "./SearchForm";
import { SourceCard } from "./SourceCard";

const MODE_LABELS: Record<InputMode, string> = {
  llm: "AI understood your topic",
  keywords: "Key words used",
  title: "Read from your brief",
  heuristic: "Read from your brief",
  direct: "Your topic",
};

const CONCEPT_SOURCE_LABELS = {
  curated: "Built-in subject knowledge",
  llm: "AI-expanded concept",
  heuristic: "Expanded from your words",
} as const;

const EXPORT_LABELS: Record<ResultsExportFormat, string> = {
  bibtex: "BibTeX",
  txt: "APA text",
  csv: "CSV",
};

export function ResearchPage() {
  const { items, savedIds, save, notify } = useLibrary();
  const {
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
  } = useResearch();
  const [savingIds, setSavingIds] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [visibleCount, setVisibleCount] = useState(RESULT_PAGE_SIZE);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const handleSave = useCallback(
    async (source: Source) => {
      if (savedIds.has(source.id)) return;
      setSavingIds((previous) => new Set(previous).add(source.id));
      try {
        await save(source);
      } finally {
        setSavingIds((previous) => {
          const next = new Set(previous);
          next.delete(source.id);
          return next;
        });
      }
    },
    [save, savedIds],
  );

  const sources = useMemo(() => {
    const list = [...(result?.sources ?? [])];
    if (sort === "citations") list.sort((a, b) => b.citation_count - a.citation_count);
    if (sort === "year") list.sort((a, b) => (b.year ?? 0) - (a.year ?? 0));
    return list;
  }, [result, sort]);

  const visibleSources = useMemo(
    () => sources.slice(0, visibleCount),
    [sources, visibleCount],
  );
  const hasMore = !loading && visibleCount < sources.length;

  // A new search or sort shows the first page again. Background note upgrades
  // do not touch searchVersion, so they never collapse a scrolled feed.
  useEffect(() => {
    setVisibleCount(RESULT_PAGE_SIZE);
  }, [searchVersion, sort]);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasMore) return;
    if (typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setVisibleCount((current) => Math.min(current + RESULT_PAGE_SIZE, sources.length));
      },
      { rootMargin: "320px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, sources.length, visibleCount]);

  const handleExport = useCallback(
    async (format: ResultsExportFormat) => {
      if (sources.length === 0) return;
      setExporting(true);
      try {
        await downloadResultsExport(sources, format);
        notify(`Exported ${sources.length} source(s) as ${EXPORT_LABELS[format]}.`);
      } catch (caught) {
        notify(caught instanceof Error ? caught.message : "The export failed.");
      } finally {
        setExporting(false);
      }
    },
    [notify, sources],
  );

  const hasActiveFilters =
    filters.open_access_only ||
    filters.reviews_only ||
    filters.exclude_preprints ||
    !filters.english_only ||
    filters.year_from !== null ||
    filters.year_to !== null ||
    filters.subject !== "any";

  const broadenSearch = () => {
    const next = { ...filters, relevance_mode: "balanced" as const };
    setFilters(next);
    void runSearch(undefined, next);
  };

  const clearFiltersAndSearch = () => {
    const next = {
      ...DEFAULT_FILTERS,
      relevance_mode: filters.relevance_mode,
      deep_search: filters.deep_search,
    };
    setFilters(next);
    void runSearch(undefined, next);
  };

  const focusSearch = () => {
    const input = document.getElementById("topic");
    input?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => input?.focus(), 250);
  };

  const seconds = result ? (result.took_ms / 1000).toFixed(1) : "0.0";
  const topicChanged =
    !!result && result.topic.trim().toLowerCase() !== result.query.trim().toLowerCase();
  const fewResults =
    !!result && !loading && !error && sources.length > 0 && sources.length <= 7;
  // The empty state already explains a zero-result search; keep provider and
  // filter warnings, but do not repeat the generic "No sources matched" line.
  const warnings = (result?.warnings ?? []).filter(
    (warning) => !(sources.length === 0 && /^no sources matched/i.test(warning)),
  );
  const conceptPlan = result?.concepts ?? [];
  const showConceptPlan =
    conceptPlan.length > 1 ||
    conceptPlan.some(
      (concept) =>
        concept.obsolete ||
        !!concept.historical ||
        concept.alternate_names.length > 0 ||
        concept.source !== "heuristic",
    );
  const conceptPlanExpands = conceptPlan.some(
    (concept) =>
      concept.obsolete || !!concept.historical || concept.alternate_names.length > 0,
  );

  return (
    <section className="page">
      <header className="page-header">
        <p className="eyebrow">Module 1</p>
        <h1>Research Source Finder</h1>
        <p className="page-subtitle">
          Search free scholarly databases, rank the strongest sources, and copy APA, MLA, or
          Chicago citations. Paste a question or a whole assignment brief.
        </p>
      </header>

      <SearchForm
        query={query}
        onQueryChange={setQuery}
        filters={filters}
        onFiltersChange={setFilters}
        onSubmit={() => void runSearch()}
        onReset={resetFilters}
        loading={loading}
        recentSearches={recentSearches}
        onClearRecents={clearRecentSearches}
        onSearchTopic={(topic) => void runSearch(topic)}
      />

      {error ? (
        <FriendlyState
          title="The search didn’t finish."
          actions={
            <button type="button" className="btn btn-small" onClick={() => void runSearch()}>
              Retry
            </button>
          }
        >
          {error}
        </FriendlyState>
      ) : null}

      {result && topicChanged ? (
        <div className="topic-banner">
          <span className="topic-badge">{MODE_LABELS[result.input_mode]}</span>
          <div className="topic-text">
            Searched for <strong>{result.topic}</strong>
          </div>
          {result.keywords.length > 0 ? (
            <div className="tag-row">
              {result.keywords.map((keyword) => (
                <span className="chip" key={keyword}>
                  {keyword}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {result && showConceptPlan ? (
        <section className="concept-plan" aria-label="Concept expansion">
          <div className="concept-plan-head">
            <div>
              <p className="eyebrow">Search plan</p>
              <h2>How I understood your topic</h2>
            </div>
            <p className="muted">
              {conceptPlanExpands
                ? "Current, historical, and alternate forms were searched so older and newer papers can both appear."
                : "These are the main concepts used to search."}
            </p>
          </div>
          <div className="concept-chip-row">
            {result.concepts.map((concept) => (
              <span
                className={`chip${concept.primary ? " chip-primary" : ""}`}
                key={`${concept.label}-${concept.source}`}
              >
                {concept.label}
                {concept.obsolete ? " · historical" : ""}
              </span>
            ))}
          </div>
          <details className="concept-details">
            <summary>Show concept details</summary>
            <div className="concept-grid">
              {result.concepts.map((concept) => (
                <article
                  className={`concept-card${concept.obsolete ? " concept-obsolete" : ""}`}
                  key={`${concept.label}-${concept.source}`}
                >
                  <header className="concept-card-head">
                    <h3>{concept.label}</h3>
                    <div className="badges">
                      {concept.primary ? (
                        <span className="badge badge-good">Main concept</span>
                      ) : null}
                      {concept.obsolete ? (
                        <span className="badge badge-warn">Obsolete term</span>
                      ) : null}
                    </div>
                  </header>
                  <p className="concept-line">
                    <span className="concept-label">Historical</span>
                    {concept.historical ?? "No separate historical meaning recorded."}
                  </p>
                  <p className="concept-line">
                    <span className="concept-label">Current</span>
                    {concept.current}
                  </p>
                  {concept.alternate_names.length > 0 ? (
                    <div className="tag-row">
                      <span className="faint">Also called</span>
                      {concept.alternate_names.map((name) => (
                        <span className="chip" key={name}>
                          {name}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <p className="concept-source">{CONCEPT_SOURCE_LABELS[concept.source]}</p>
                </article>
              ))}
            </div>
          </details>
        </section>
      ) : null}

      {!error && warnings.length > 0 ? (
        <div className="banner banner-warn">
          <strong>Heads up</strong>
          <ul>
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="results-toolbar">
        <div className="muted">
          {loading
            ? "Searching scholarly databases…"
            : result
              ? `${result.count} strong source${result.count === 1 ? "" : "s"} · ${seconds}s ${
                  result.cached ? "· cached" : ""
                }`
              : "Search to build your source list."}
        </div>
        <div className="toolbar-actions">
          {result ? (
            <>
              <label className="faint" htmlFor="sort">
                Sort
              </label>
              <select
                id="sort"
                className="select select-inline"
                value={sort}
                onChange={(event) => setSort(event.target.value as SortMode)}
              >
                <option value="match">Best match</option>
                <option value="citations">Most cited</option>
                <option value="year">Newest first</option>
              </select>
              {sources.length > 0 ? (
                <select
                  className="select select-inline"
                  value=""
                  onChange={(event) => {
                    const format = event.target.value as ResultsExportFormat;
                    if (format) void handleExport(format);
                  }}
                  aria-label="Export results"
                  disabled={exporting}
                >
                  <option value="" disabled>
                    {exporting ? "Exporting…" : "Export…"}
                  </option>
                  <option value="bibtex">BibTeX</option>
                  <option value="txt">APA text</option>
                  <option value="csv">CSV</option>
                </select>
              ) : null}
            </>
          ) : null}
          <Link className="btn btn-small" to="/library">
            <Icon name="book" size={15} /> Library ({items.length})
          </Link>
        </div>
      </div>

      {fewResults ? (
        <FriendlyState
          compact
          title={`Only ${sources.length} strong match${sources.length === 1 ? "" : "es"} this time.`}
          actions={
            <>
              {filters.relevance_mode === "strict" ? (
                <button type="button" className="btn btn-small" onClick={broadenSearch}>
                  Try more results
                </button>
              ) : null}
              {hasActiveFilters ? (
                <button
                  type="button"
                  className="btn btn-small btn-ghost"
                  onClick={clearFiltersAndSearch}
                >
                  Clear filters
                </button>
              ) : null}
            </>
          }
        >
          {hasActiveFilters
            ? "We’d rather show a few solid sources than pad the list. Try a broader topic or turn off a filter."
            : "We’d rather show a few solid sources than pad the list. Try a broader topic."}
        </FriendlyState>
      ) : null}

      <div className="results-list">
        {loading
          ? [0, 1, 2].map((index) => <div className="skeleton" key={index} />)
          : visibleSources.map((source, index) => (
              <SourceCard
                key={source.id}
                source={source}
                rank={index + 1}
                saved={savedIds.has(source.id)}
                saving={savingIds.has(source.id)}
                onSave={handleSave}
                onRelated={setRelatedSource}
              />
            ))}

        {hasMore ? <div ref={sentinelRef} className="results-sentinel" aria-hidden="true" /> : null}

        {!loading && !error && result && sources.length === 0 ? (
          <FriendlyState
            title="No strong matches this time."
            actions={
              <>
                {hasActiveFilters ? (
                  <button
                    type="button"
                    className="btn btn-small"
                    onClick={clearFiltersAndSearch}
                  >
                    Clear filters
                  </button>
                ) : null}
                <button type="button" className="btn btn-small btn-ghost" onClick={focusSearch}>
                  Try a popular topic
                </button>
              </>
            }
          >
            {hasActiveFilters
              ? "Try different words, a broader topic, or remove a filter. The popular topics above are a good place to start."
              : "Try different words or a broader topic. The popular topics above are a good place to start."}
          </FriendlyState>
        ) : null}

        {!loading && !error && !result ? (
          <div className="empty-state empty-hero">
            <div className="empty-hero-mark">
              <Icon name="search" size={26} />
            </div>
            <h2>Find real, citable sources in seconds</h2>
            <p className="muted">
              Type any topic or paste your activity brief. Every result comes with a match score,
              a credibility check, an AI relevance note, and ready-to-copy APA / MLA / Chicago
              citations.
            </p>
          </div>
        ) : null}
      </div>

      {relatedSource ? (
        <RelatedModal
          source={relatedSource}
          savedIds={savedIds}
          onClose={() => setRelatedSource(null)}
          onSave={handleSave}
        />
      ) : null}
    </section>
  );
}
