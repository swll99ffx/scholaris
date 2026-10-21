import { useEffect, useMemo, useState } from "react";

import type { ExportFormat, LibraryItem } from "../../api/types";
import { Icon } from "../../components/Icon";
import { useLibrary } from "./LibraryContext";

interface Draft {
  notes: string;
  tags: string;
}

export function LibraryPage() {
  const { items, loading, exporting, update, remove, exportAs, notify } = useLibrary();
  const [filter, setFilter] = useState("");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  // Keep drafts in sync with the latest data from the server.
  useEffect(() => {
    const next: Record<string, Draft> = {};
    for (const item of items) {
      next[item.library_id] = { notes: item.notes, tags: item.tags.join(", ") };
    }
    setDrafts(next);
  }, [items]);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((item) => {
      const haystack = [item.title, item.authors.join(" "), item.tags.join(" "), item.notes]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [items, filter]);

  const copyAllApa = async () => {
    if (items.length === 0) return;
    const text = items
      .map((item) => item.citation_styles.apa)
      .filter(Boolean)
      .join("\n\n");
    try {
      await navigator.clipboard.writeText(text);
      notify("Copied every APA citation");
    } catch {
      notify("Your browser blocked the clipboard. Use the export menu instead.");
    }
  };

  const allTags = useMemo(
    () => Array.from(new Set(items.flatMap((item) => item.tags))).sort(),
    [items],
  );

  return (
    <section className="page">
      <header className="page-header">
        <p className="eyebrow">Tools</p>
        <h1>My Library</h1>
        <p className="page-subtitle">
          Everything you saved — your Review of Related Literature. Add notes and tags, then export
          the whole bibliography as BibTeX, text, or a Word document.
        </p>
      </header>

      <div className="card library-toolbar">
        <div className="toolbar-actions">
          <strong>{items.length} saved source(s)</strong>
          {allTags.length > 0 ? (
            <div className="tag-row">
              {allTags.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  className="chip chip-button"
                  onClick={() => setFilter(tag)}
                >
                  {tag}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="toolbar-actions">
          <input
            className="input input-compact"
            value={filter}
            placeholder="Filter by title, author, tag or note…"
            onChange={(event) => setFilter(event.target.value)}
          />
          <button
            type="button"
            className="btn btn-small"
            disabled={items.length === 0}
            onClick={copyAllApa}
          >
            <Icon name="copy" size={14} /> Copy all APA
          </button>
          <select
            className="select select-inline"
            value={exporting ?? ""}
            onChange={(event) => {
              const format = event.target.value as ExportFormat;
              if (format) void exportAs(format);
            }}
            disabled={items.length === 0 || exporting !== null}
            aria-label="Export library"
            title="Export the whole library"
          >
            <option value="" disabled>
              {exporting ? `Exporting ${exporting.toUpperCase()}…` : "Export…"}
            </option>
            <option value="bibtex">BibTeX</option>
            <option value="txt">Text / APA</option>
            <option value="docx">Word (.docx)</option>
            <option value="csv">CSV</option>
          </select>
        </div>
      </div>

      {loading && items.length === 0 ? <div className="skeleton" /> : null}

      {!loading && items.length === 0 ? (
        <div className="empty-state empty-hero">
          <div className="empty-hero-mark">
            <Icon name="book" size={26} />
          </div>
          <h2>Your library is empty</h2>
          <p className="muted">
            Save a source from the Source Finder and it will appear here, ready to cite.
          </p>
        </div>
      ) : null}

      <div className="results-list">
        {visible.map((item) => (
          <LibraryCard
            key={item.library_id}
            item={item}
            draft={drafts[item.library_id] ?? { notes: item.notes, tags: item.tags.join(", ") }}
            onDraftChange={(draft) =>
              setDrafts((current) => ({ ...current, [item.library_id]: draft }))
            }
            onSave={() => {
              const draft = drafts[item.library_id] ?? { notes: item.notes, tags: item.tags.join(", ") };
              void update(item.library_id, {
                notes: draft.notes,
                tags: draft.tags
                  .split(",")
                  .map((tag) => tag.trim())
                  .filter(Boolean),
              });
            }}
            confirming={confirmingId === item.library_id}
            onRequestRemove={() => setConfirmingId(item.library_id)}
            onCancelRemove={() => setConfirmingId(null)}
            onConfirmRemove={() => {
              setConfirmingId(null);
              void remove(item.library_id);
            }}
          />
        ))}
      </div>

      {!loading && items.length > 0 && visible.length === 0 ? (
        <div className="empty-state">No saved source matches “{filter}”.</div>
      ) : null}
    </section>
  );
}

interface LibraryCardProps {
  item: LibraryItem;
  draft: Draft;
  confirming: boolean;
  onDraftChange: (draft: Draft) => void;
  onSave: () => void;
  onRequestRemove: () => void;
  onCancelRemove: () => void;
  onConfirmRemove: () => void;
}

function LibraryCard({
  item,
  draft,
  confirming,
  onDraftChange,
  onSave,
  onRequestRemove,
  onCancelRemove,
  onConfirmRemove,
}: LibraryCardProps) {
  const url = item.url || (item.doi ? `https://doi.org/${item.doi}` : undefined);

  return (
    <article className="source-card">
      <div className="source-head">
        <div>
          <h3 className="source-title">
            {url ? (
              <a href={url} target="_blank" rel="noreferrer">
                {item.title} <Icon name="external" size={13} />
              </a>
            ) : (
              item.title
            )}
          </h3>
          <p className="source-meta">
            {item.authors[0] ?? "Unknown author"}
            {item.authors.length > 1 ? ", et al." : ""} · {item.year ?? "n.d."}
            {item.journal ? ` · ${item.journal}` : ""}
          </p>
        </div>
        {confirming ? (
          <div className="confirm-remove">
            <span>Remove this source?</span>
            <button
              type="button"
              className="btn btn-small btn-danger"
              onClick={onConfirmRemove}
            >
              <Icon name="check" size={14} /> Remove
            </button>
            <button type="button" className="btn btn-small btn-ghost" onClick={onCancelRemove}>
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="icon-button"
            aria-label="Remove from library"
            onClick={onRequestRemove}
          >
            <Icon name="trash" size={17} />
          </button>
        )}
      </div>

      {item.tags.length > 0 ? (
        <div className="tag-row">
          {item.tags.map((tag) => (
            <span className="chip" key={tag}>
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      {item.author_check.status === "needs_checking" ? (
        <div className="banner banner-warn author-warning" role="status">
          <strong>Author names need checking.</strong>{" "}
          {item.author_check.reason ||
            "The provider records disagree on the author list. Verify the citation before submitting."}
        </div>
      ) : null}

      <p className="citation-text">{item.citation_styles.apa}</p>

      <div className="library-fields">
        <div className="field">
          <label htmlFor={`notes-${item.library_id}`}>Notes / RRL sentence</label>
          <textarea
            id={`notes-${item.library_id}`}
            className="textarea"
            value={draft.notes}
            placeholder="How does this source support your argument?"
            onChange={(event) => onDraftChange({ ...draft, notes: event.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor={`tags-${item.library_id}`}>Tags (comma separated)</label>
          <input
            id={`tags-${item.library_id}`}
            className="input"
            value={draft.tags}
            placeholder="methods, background, key-source"
            onChange={(event) => onDraftChange({ ...draft, tags: event.target.value })}
          />
        </div>
      </div>

      <div className="card-actions">
        <button type="button" className="btn btn-small" onClick={onSave}>
          <Icon name="check" size={14} /> Save changes
        </button>
        <button
          type="button"
          className="btn btn-small"
          onClick={() => {
            void navigator.clipboard.writeText(item.citation_styles.apa);
          }}
        >
          <Icon name="copy" size={14} /> Copy APA
        </button>
      </div>
    </article>
  );
}
