import type { RelevanceMode, SearchFilters } from "../../api/types";
import { Icon } from "../../components/Icon";

interface SearchFormProps {
  query: string;
  onQueryChange: (value: string) => void;
  filters: SearchFilters;
  onFiltersChange: (filters: SearchFilters) => void;
  onSubmit: () => void;
  onReset: () => void;
  loading: boolean;
  recentSearches: string[];
  onClearRecents: () => void;
  onSearchTopic: (topic: string) => void;
}

const POPULAR_TOPICS = [
  "CRISPR gene editing",
  "sleep and temperature",
  "social media and student focus",
  "quantum entanglement",
  "antibiotic resistance",
  "climate feedback loops",
];

const RELEVANCE_OPTIONS: Array<{ value: RelevanceMode; label: string }> = [
  { value: "strict", label: "Best match" },
  { value: "balanced", label: "More results" },
];

export function SearchForm({
  query,
  onQueryChange,
  filters,
  onFiltersChange,
  onSubmit,
  onReset,
  loading,
  recentSearches,
  onClearRecents,
  onSearchTopic,
}: SearchFormProps) {
  const update = <K extends keyof SearchFilters>(key: K, value: SearchFilters[K]) => {
    onFiltersChange({ ...filters, [key]: value });
  };

  const activeFilterCount =
    Number(filters.open_access_only) +
    Number(filters.reviews_only) +
    Number(filters.exclude_preprints) +
    Number(!filters.english_only) +
    Number(filters.year_from !== null) +
    Number(filters.year_to !== null) +
    Number(filters.subject !== "any");

  return (
    <form
      className="card search-card"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label className="field-label" htmlFor="topic">
        Topic, question, or assignment brief
      </label>
      <textarea
        id="topic"
        className="textarea topic-input"
        value={query}
        rows={3}
        placeholder="Ask a question, type keywords, or paste an assignment / lab brief — I'll find the topic and cite real papers."
        onChange={(event) => onQueryChange(event.target.value)}
        onKeyDown={(event) => {
          // Enter searches; Shift+Enter inserts a newline for long briefs.
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            onSubmit();
          }
        }}
      />

      <div className="search-preferences">
        <div className="preference">
          <span className="preference-label">Relevance</span>
          <div className="segmented" role="group" aria-label="Relevance mode">
            {RELEVANCE_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`segment ${filters.relevance_mode === option.value ? "segment-active" : ""}`}
                aria-pressed={filters.relevance_mode === option.value}
                onClick={() => update("relevance_mode", option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <p className="preference-hint">
          {filters.relevance_mode === "strict"
            ? "Best match hides borderline papers so every result is clearly on topic."
            : "More results keeps broader matches, including papers that only partly fit."}
        </p>
      </div>

      <div className="search-actions">
        <button
          type="submit"
          className="btn btn-primary btn-large"
          disabled={loading || query.trim().length < 2}
        >
          {loading ? (
            <>
              <span className="spinner" /> Finding sources…
            </>
          ) : (
            <>
              <Icon name="search" size={17} /> Search &amp; cite
            </>
          )}
        </button>

        <button
          type="button"
          className="btn btn-toggle"
          aria-pressed={filters.deep_search}
          onClick={() => update("deep_search", !filters.deep_search)}
          title="Also searches slower open-access repositories. This can take up to about 20 seconds."
        >
          Deep search {filters.deep_search ? "on" : "off"}
        </button>

        <details className="advanced">
          <summary>
            Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
          </summary>
          <div className="advanced-body">
            <label className="check">
              <input
                type="checkbox"
                checked={filters.open_access_only}
                onChange={(event) => update("open_access_only", event.target.checked)}
              />
              Free to read only
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={filters.reviews_only}
                onChange={(event) => update("reviews_only", event.target.checked)}
              />
              Reviews &amp; meta-analyses only
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={filters.exclude_preprints}
                onChange={(event) => update("exclude_preprints", event.target.checked)}
              />
              Exclude preprints
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={filters.english_only}
                onChange={(event) => update("english_only", event.target.checked)}
              />
              English sources only
            </label>
            <button type="button" className="btn btn-ghost btn-small" onClick={onReset}>
              Reset filters
            </button>
          </div>
        </details>
      </div>

      <div className="search-suggestions">
        {recentSearches.length > 0 ? (
          <div className="suggestion-row" aria-label="Recent searches">
            <span className="suggestion-label">Recent</span>
            {recentSearches.map((topic) => (
              <button
                key={topic}
                type="button"
                className="chip chip-button"
                onClick={() => onSearchTopic(topic)}
                title={`Search again for ${topic}`}
              >
                {topic}
              </button>
            ))}
            <button type="button" className="link-button suggestion-clear" onClick={onClearRecents}>
              Clear
            </button>
          </div>
        ) : null}

        <div className="suggestion-row" aria-label="Popular topics">
          <span className="suggestion-label">Popular</span>
          {POPULAR_TOPICS.map((topic) => (
            <button
              key={topic}
              type="button"
              className="chip chip-button"
              onClick={() => onSearchTopic(topic)}
              title={`Search for ${topic}`}
            >
              {topic}
            </button>
          ))}
        </div>
      </div>
    </form>
  );
}
