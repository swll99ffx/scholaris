import type {
  ExportFormat,
  Health,
  LibraryItem,
  LibraryListResponse,
  NotesResponse,
  RelatedRequest,
  RelatedResponse,
  ResultsExportFormat,
  SaveSummaryResponse,
  SearchFilters,
  SearchResponse,
  SummarizeTextRequest,
  Summary,
  SummarySourceMeta,
} from "./types";

// Where is the Python backend?
//  * If VITE_API_URL is set (frontend/.env), use it.
//  * Otherwise default to port 8000 on the SAME host you opened the page from,
//    so opening the app on your phone via your PC's LAN IP just works.
const envBase = (import.meta.env.VITE_API_URL as string | undefined)?.trim();

export function apiBase(): string {
  if (envBase) {
    return envBase.replace(/\/+$/, "");
  }
  if (typeof window !== "undefined" && window.location.hostname) {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        message = body.detail;
      } else if (Array.isArray(body.detail) && body.detail.length > 0) {
        const first = body.detail[0] as { msg?: string };
        if (first?.msg) message = first.msg;
      }
    } catch {
      // Response was not JSON; keep the generic message.
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function fetchHealth(): Promise<Health> {
  const response = await fetch(`${apiBase()}/api/health`);
  return parseResponse<Health>(response);
}

export async function searchSources(
  query: string,
  filters: SearchFilters,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const response = await fetch(`${apiBase()}/api/research/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, filters }),
    signal,
  });
  return parseResponse<SearchResponse>(response);
}

export async function fetchNotes(
  query: string,
  sources: SearchResponse["sources"],
  signal?: AbortSignal,
): Promise<NotesResponse> {
  const response = await fetch(`${apiBase()}/api/research/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, sources }),
    signal,
  });
  return parseResponse<NotesResponse>(response);
}

export async function downloadResultsExport(
  sources: SearchResponse["sources"],
  format: ResultsExportFormat,
): Promise<void> {
  const response = await fetch(`${apiBase()}/api/research/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sources, format }),
  });
  if (!response.ok) {
    await parseResponse(response); // throws with a friendly message
  }
  const blob = await response.blob();
  const today = new Date().toISOString().slice(0, 10);
  const extension = format === "bibtex" ? "bib" : format;
  const filename = `scholaris-results-${today}.${extension}`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function findRelated(request: RelatedRequest): Promise<RelatedResponse> {
  const response = await fetch(`${apiBase()}/api/research/related`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return parseResponse<RelatedResponse>(response);
}

export async function listLibrary(): Promise<LibraryListResponse> {
  const response = await fetch(`${apiBase()}/api/research/library`);
  return parseResponse<LibraryListResponse>(response);
}

export async function saveToLibrary(
  source: LibraryItem | SearchResponseSources,
  notes = "",
  tags: string[] = [],
): Promise<LibraryItem> {
  const response = await fetch(`${apiBase()}/api/research/library`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, notes, tags }),
  });
  return parseResponse<LibraryItem>(response);
}

// The save endpoint accepts the same Source shape returned by search.
type SearchResponseSources = SearchResponse["sources"][number];

export async function updateLibraryItem(
  libraryId: string,
  updates: { notes?: string; tags?: string[] },
): Promise<LibraryItem> {
  const response = await fetch(`${apiBase()}/api/research/library/${encodeURIComponent(libraryId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  return parseResponse<LibraryItem>(response);
}

export async function deleteLibraryItem(libraryId: string): Promise<void> {
  const response = await fetch(`${apiBase()}/api/research/library/${encodeURIComponent(libraryId)}`, {
    method: "DELETE",
  });
  return parseResponse<void>(response);
}

export async function downloadLibraryExport(format: ExportFormat): Promise<void> {
  const response = await fetch(`${apiBase()}/api/research/library/export?format=${format}`);
  if (!response.ok) {
    await parseResponse(response); // throws with a friendly message
  }
  const blob = await response.blob();
  const today = new Date().toISOString().slice(0, 10);
  const extension = format === "bibtex" ? "bib" : format;
  const filename = `scholaris-rrl-${today}.${extension}`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------- Module 2

export async function summarizeText(request: SummarizeTextRequest): Promise<Summary> {
  const response = await fetch(`${apiBase()}/api/summarize/text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return parseResponse<Summary>(response);
}

export async function summarizePdf(
  file: File,
  source: SummarySourceMeta,
  quoteCount: number,
): Promise<Summary> {
  const form = new FormData();
  form.append("file", file);
  form.append("title", source.title);
  form.append("authors", source.authors.join(", "));
  form.append("year", source.year ? String(source.year) : "");
  form.append("journal", source.journal ?? "");
  form.append("doi", source.doi ?? "");
  form.append("url", source.url ?? "");
  form.append("quote_count", String(quoteCount));

  const response = await fetch(`${apiBase()}/api/summarize/pdf`, {
    method: "POST",
    body: form,
  });
  return parseResponse<Summary>(response);
}

export async function saveSummary(
  summary: Summary,
  libraryId: string | null,
): Promise<SaveSummaryResponse> {
  const response = await fetch(`${apiBase()}/api/summarize/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ summary, library_id: libraryId }),
  });
  return parseResponse<SaveSummaryResponse>(response);
}
