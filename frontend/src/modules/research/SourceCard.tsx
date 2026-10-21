import { useState } from "react";
import { useNavigate } from "react-router-dom";

import type { CredibilityStatus, Source } from "../../api/types";
import { Icon } from "../../components/Icon";
import { CitationTabs } from "./CitationTabs";

interface SourceCardProps {
  source: Source;
  rank: number;
  saved: boolean;
  saving: boolean;
  onSave: (source: Source) => void;
  onRelated: (source: Source) => void;
}

const PROVIDER_LABELS: Record<string, string> = {
  openalex: "OpenAlex",
  europepmc: "Europe PMC",
  semantic_scholar: "Semantic Scholar",
  crossref: "Crossref",
  pubmed: "PubMed",
  doaj: "DOAJ",
  core: "CORE",
};

const CHECK_MARKS: Record<CredibilityStatus, string> = {
  good: "✓",
  warn: "!",
  unknown: "?",
};

const BREAKDOWN_LABELS: Record<string, string> = {
  relevance: "Relevance",
  citations: "Citations",
  recency: "Recency",
  review: "Review / textbook",
  foundational: "Foundational",
  scope: "Scope / centrality",
};

function formatAuthors(authors: string[]): string {
  if (authors.length === 0) return "Unknown authors";
  const shown = authors.slice(0, 4).join(", ");
  return authors.length > 4 ? `${shown}, et al.` : shown;
}

export function SourceCard({ source, rank, saved, saving, onSave, onRelated }: SourceCardProps) {
  const [expanded, setExpanded] = useState(false);
  const navigate = useNavigate();
  const abstract = source.abstract || "No abstract was available from these providers.";
  const externalUrl = source.url || (source.doi ? `https://doi.org/${source.doi}` : null);
  const goodChecks = source.credibility.filter((item) => item.status === "good").length;
  const warnChecks = source.credibility.filter((item) => item.status === "warn").length;
  const unknownChecks = source.credibility.filter((item) => item.status === "unknown").length;
  const checkSummary = [
    goodChecks > 0 ? `${goodChecks} good` : "",
    warnChecks > 0 ? `${warnChecks} warning${warnChecks === 1 ? "" : "s"}` : "",
    unknownChecks > 0 ? `${unknownChecks} unclear` : "",
  ]
    .filter(Boolean)
    .join(", ");
  const providerNames = source.providers
    .map((provider) => PROVIDER_LABELS[provider] ?? provider)
    .join(" · ");

  return (
    <article className="source-card">
      <div className="source-head">
        <div>
          <h3 className="source-title">
            {externalUrl ? (
              <a href={externalUrl} target="_blank" rel="noreferrer">
                {source.title} <Icon name="external" size={13} />
              </a>
            ) : (
              source.title
            )}
          </h3>
          <p className="source-meta">
            {formatAuthors(source.authors)} · {source.year ?? "n.d."}
            {source.journal ? ` · ${source.journal}` : ""}
          </p>
        </div>
        <div className="score-pill" title="Overall ranking score (0–100)">
          <div className="score-value">{Math.round(source.score)}</div>
          <div className="score-label">Match</div>
        </div>
      </div>

      <div className="badges">
        <span className="badge badge-rank">#{rank}</span>
        <span
          className={`badge ${source.citation_count >= 100 ? "badge-cited" : ""}`}
          title="Times cited (from OpenAlex / Semantic Scholar / Europe PMC)"
        >
          {source.citation_count.toLocaleString()} citations
        </span>
        {source.is_review ? <span className="badge badge-good">Review article</span> : null}
        {source.is_retracted ? <span className="badge badge-warn">Retracted</span> : null}
        {source.is_non_primary ? <span className="badge badge-warn">Meeting report</span> : null}
        {source.is_preprint ? <span className="badge badge-warn">Preprint</span> : null}
        {source.is_administrative ? (
          <span className="badge badge-warn">Administrative notice</span>
        ) : null}
        {source.is_open_access ? <span className="badge badge-good">Open access</span> : null}
      </div>

      {source.author_check.status === "needs_checking" ? (
        <div className="banner banner-warn author-warning" role="status">
          <strong>Author names need checking.</strong>{" "}
          {source.author_check.reason ||
            "The provider records disagree on the author list. The citation is marked so you can verify it."}
        </div>
      ) : null}

      <p className={`abstract ${expanded ? "" : "abstract-clamped"}`}>{abstract}</p>
      {abstract.length > 280 ? (
        <button type="button" className="link-button" onClick={() => setExpanded((value) => !value)}>
          {expanded ? "Show less" : "Show more"}
        </button>
      ) : null}

      <div className="ai-note">
        <div className="ai-note-head">
          <Icon name="check" size={13} /> AI relevance note
          {source.ai_note_source === "heuristic" ? " (quick)" : ""}
        </div>
        {source.ai_note}
      </div>

      <details className="source-details">
        <summary>Why this result</summary>
        <div className="source-details-body">
          {source.matched_terms.length > 0 ? (
            <div className="matched-row" title="The query words this source actually covers">
              <span className="matched-label">Matched on</span>
              {source.matched_terms.map((term) => (
                <span className="badge badge-match" key={term}>
                  {term}
                </span>
              ))}
            </div>
          ) : null}
          <p className="reason">{source.reason}</p>
          {Object.keys(source.score_breakdown).length > 0 ? (
            <div className="score-breakdown">
              {Object.entries(source.score_breakdown).map(([key, value]) => (
                <div className="meter" key={key}>
                  <div className="meter-head">
                    <span>{BREAKDOWN_LABELS[key] ?? key}</span>
                    <span>{Math.round(value)}</span>
                  </div>
                  <div className="meter-track">
                    <div
                      className="meter-fill"
                      style={{ width: `${Math.max(2, Math.min(100, value))}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </details>

      <details className="source-details">
        <summary>
          Credibility checks{checkSummary ? ` · ${checkSummary}` : ""}
        </summary>
        <div className="checklist">
          {source.credibility.map((item) => (
            <div className="check-item" key={item.label}>
              <span className={`check-dot check-${item.status}`}>{CHECK_MARKS[item.status]}</span>
              <span>
                <span className="check-label">{item.label}:</span> {item.detail}
              </span>
            </div>
          ))}
        </div>
      </details>

      <details className="source-details">
        <summary>Source details</summary>
        <div className="source-details-body">
          <p className="source-providers">
            <strong>Found in:</strong> {providerNames || "Provider not recorded"}
          </p>
          {source.doi ? (
            <p className="source-providers">
              <strong>DOI:</strong>{" "}
              <a href={`https://doi.org/${source.doi}`} target="_blank" rel="noreferrer">
                {source.doi}
              </a>
            </p>
          ) : null}
        </div>
      </details>

      <CitationTabs styles={source.citation_styles} />

      <div className="card-actions">
        <button
          type="button"
          className="btn btn-small"
          disabled={saving || saved}
          onClick={() => onSave(source)}
        >
          <Icon name={saved ? "check" : "plus"} size={15} />
          {saved ? "Saved" : saving ? "Saving…" : "Save to library"}
        </button>
        <button type="button" className="btn btn-small" onClick={() => onRelated(source)}>
          Find related sources
        </button>
        {source.abstract ? (
          <button
            type="button"
            className="btn btn-small"
            onClick={() =>
              navigate("/summarize", {
                state: {
                  prefill: {
                    text: source.abstract,
                    title: source.title,
                    authors: source.authors,
                    year: source.year,
                    journal: source.journal,
                    doi: source.doi,
                    url: source.url,
                  },
                  libraryId: saved ? source.id : null,
                },
              })
            }
          >
            <Icon name="summary" size={15} /> Summarize
          </button>
        ) : null}
      </div>
    </article>
  );
}
