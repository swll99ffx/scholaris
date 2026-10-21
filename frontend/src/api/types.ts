// Shared types mirroring the FastAPI schemas (Module 1).

export type CredibilityStatus = "good" | "warn" | "unknown";
export type AiNoteSource = "llm" | "heuristic";
export type SubjectFilter = "any" | "science" | "math" | "biology" | "general";
export type RelevanceMode = "strict" | "balanced";
// How the backend turned the input into a search topic.
export type InputMode = "direct" | "keywords" | "title" | "heuristic" | "llm";

export interface CredibilityItem {
  label: string;
  status: CredibilityStatus;
  detail: string;
}

export interface CitationStyles {
  apa: string;
  mla: string;
  chicago: string;
}

export type ConceptSource = "curated" | "heuristic" | "llm";

export interface Concept {
  label: string;
  historical: string | null;
  current: string;
  alternate_names: string[];
  obsolete: boolean;
  primary: boolean;
  source: ConceptSource;
}

export interface AuthorDetail {
  family: string;
  given: string;
  literal: string;
  suffix: string;
  orcid: string | null;
  source: string;
}

export type AuthorCheckStatus = "ok" | "needs_checking";

export interface AuthorCheck {
  status: AuthorCheckStatus;
  reason: string;
  conflicts: string[];
}

export interface Source {
  id: string;
  title: string;
  authors: string[];
  author_details: AuthorDetail[];
  author_check: AuthorCheck;
  year: number | null;
  journal: string | null;
  abstract: string;
  url: string | null;
  doi: string | null;
  language: string | null;
  citation_count: number;
  is_open_access: boolean | null;
  is_review: boolean | null;
  is_retracted: boolean;
  is_preprint: boolean;
  is_non_primary: boolean;
  work_type: string | null;
  volume: string | null;
  issue: string | null;
  pages: string | null;
  article_number: string | null;
  publisher: string | null;
  subjects: string[];
  providers: string[];
  provider_ids: Record<string, string>;
  discovery: string | null;
  score: number;
  score_breakdown: Record<string, number>;
  is_administrative: boolean;
  matched_terms: string[];
  reason: string;
  ai_note: string;
  ai_note_source: AiNoteSource;
  credibility: CredibilityItem[];
  citation_styles: CitationStyles;
}

export interface SearchFilters {
  year_from: number | null;
  year_to: number | null;
  reviews_only: boolean;
  open_access_only: boolean;
  english_only: boolean;
  subject: SubjectFilter;
  relevance_mode: RelevanceMode;
  limit: number;
  deep_search: boolean;
  exclude_preprints: boolean;
}

export interface SearchResponse {
  query: string;
  // The topic actually searched for (differs from `query` when the input was a
  // casual question or a pasted assignment brief).
  topic: string;
  input_mode: InputMode;
  keywords: string[];
  concepts: Concept[];
  count: number;
  sources: Source[];
  warnings: string[];
  took_ms: number;
  cached: boolean;
}

export interface Health {
  status: string;
  app: string;
  version: string;
  ai: "key" | "free" | "off";
}

export interface RelatedResponse extends SearchResponse {
  parent_title: string;
}

export interface RelatedRequest {
  doi?: string | null;
  openalex_id?: string | null;
  title?: string | null;
  limit?: number;
}

export interface LibraryItem extends Source {
  library_id: string;
  notes: string;
  tags: string[];
  saved_at: string;
}

export interface LibraryListResponse {
  count: number;
  sources: LibraryItem[];
}

export type ExportFormat = "bibtex" | "txt" | "docx" | "csv";
export type ResultsExportFormat = "bibtex" | "txt" | "csv";
export type SortMode = "match" | "citations" | "year";

export interface NoteItem {
  id: string;
  note: string;
  source: AiNoteSource;
}

export interface NotesResponse {
  notes: NoteItem[];
}

// ---------------------------------------------------------------- Module 2

export type SummaryAiSource = "llm" | "heuristic";

export interface SummarySourceMeta {
  title: string;
  authors: string[];
  year: number | null;
  journal: string | null;
  doi: string | null;
  url: string | null;
}

export interface SummaryQuote {
  text: string;
  page: number | null;
  note: string;
}

export interface Summary {
  source: SummarySourceMeta;
  tldr: string;
  key_points: string[];
  methods: string[];
  findings: string[];
  limitations: string[];
  quotes: SummaryQuote[];
  excerpt: string;
  ai_source: SummaryAiSource;
  word_count: number;
  page_count: number | null;
  truncated: boolean;
  warnings: string[];
  took_ms: number;
}

export interface SummarizeTextRequest {
  text: string;
  source: SummarySourceMeta;
  quote_count: number;
}

export interface SaveSummaryResponse {
  library_id: string;
  title: string;
  created: boolean;
  message: string;
}

// ---------------------------------------------------------------- access gate

export interface AccessStatus {
  required: boolean;
  authenticated: boolean;
}
