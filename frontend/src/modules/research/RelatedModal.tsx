import { useEffect, useState } from "react";

import { findRelated } from "../../api/client";
import type { RelatedResponse, Source } from "../../api/types";
import { Icon } from "../../components/Icon";

interface RelatedModalProps {
  source: Source;
  savedIds: Set<string>;
  onClose: () => void;
  onSave: (source: Source) => void;
}

export function RelatedModal({ source, savedIds, onClose, onSave }: RelatedModalProps) {
  const [data, setData] = useState<RelatedResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);

    findRelated({
      doi: source.doi,
      openalex_id: source.provider_ids?.openalex ?? null,
      title: source.title,
      limit: 15,
    })
      .then((response) => {
        if (!cancelled) setData(response);
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Could not load related sources.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [source]);

  return (
    <>
      <div className="modal-backdrop" role="presentation" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-label="Related sources">
        <div className="modal-header">
          <div>
            <h2 className="card-title">Related sources</h2>
            <p className="faint">Based on: {source.title}</p>
          </div>
          <button type="button" className="icon-button" aria-label="Close" onClick={onClose}>
            <Icon name="close" size={20} />
          </button>
        </div>

        <div className="modal-body">
          {loading ? <div className="skeleton" style={{ height: 120 }} /> : null}
          {error ? <div className="banner banner-error">{error}</div> : null}
          {(data?.warnings ?? []).map((warning) => (
            <div className="banner banner-warn" key={warning}>
              {warning}
            </div>
          ))}

          {data?.sources.map((related) => (
            <div className="related-item" key={related.id}>
              <a href={related.url ?? undefined} target="_blank" rel="noreferrer">
                {related.title}
              </a>
              <div className="faint">
                {related.year ?? "n.d."}
                {related.journal ? ` · ${related.journal}` : ""} · {related.citation_count.toLocaleString()} citations ·
                match {Math.round(related.score)}
              </div>
              {related.discovery ? <span className="badge">{related.discovery}</span> : null}
              <div className="card-actions">
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={savedIds.has(related.id)}
                  onClick={() => onSave(related)}
                >
                  <Icon name={savedIds.has(related.id) ? "check" : "plus"} size={14} />
                  {savedIds.has(related.id) ? "Saved" : "Save"}
                </button>
              </div>
            </div>
          ))}

          {!loading && data && data.sources.length === 0 ? (
            <div className="empty-state">No related sources were found for this paper yet.</div>
          ) : null}
        </div>
      </div>
    </>
  );
}
