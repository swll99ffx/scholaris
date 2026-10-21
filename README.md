# Scholaris

[![CI](https://github.com/swll99ffx/scholaris/actions/workflows/ci.yml/badge.svg)](https://github.com/swll99ffx/scholaris/actions/workflows/ci.yml)

**Study smarter, not harder.** A free, cross-platform study assistant built as a **responsive PWA** (one link works on
desktop, Android and iPhone) with a **FastAPI** backend, plus a **Tauri desktop wrapper**
that is added at the packaging step.

| Layer    | Technology                      | Why                                                      |
| -------- | ------------------------------- | -------------------------------------------------------- |
| Frontend | React + TypeScript + Vite (PWA) | One codebase for web, mobile and desktop                 |
| Backend  | Python + FastAPI + httpx        | Best free libraries for research, math, data and biology |
| Storage  | SQLite                          | Zero-setup, portable personal library                    |
| Desktop  | Tauri (planned step)            | Native window around the same UI                         |

## Module status

- [x] **Module 1 — Research Source Finder** (built)
- [x] **Module 2 — Source Summarizer** (built)
- [ ] Module 3 — Pre-Calculus & Physics
- [ ] Module 4 — Data Analyst
- [ ] Module 5 — Biology
- [ ] Module 6 — AI Study Chat

Modules are built one at a time so each can be tested before the next starts.

The repository is **source-first**: run it on your own machine or local network with the setup
instructions below, or follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) to put it online for
**$0** on Oracle Cloud Always Free, behind one shared access code.

## What Module 1 does

- **Understands your topic.** Type a question, keywords, or paste an entire activity / lab
  brief. The app finds the real topic (a `Title:` line wins) before searching. AI rewrites casual
  questions or unknown topics into research phrases ("why do we feel sleepy when it's hot" →
  _ambient temperature and sleep regulation_), while well-covered school topics skip the AI call
  so results appear faster.
- **Expands the concept before searching.** The Research page shows a concept panel with each
  concept's **historical meaning**, **current meaning or replacement**, and **alternate
  names**. It then runs separate searches for modern wording, historical terms, each concept,
  and the relationship between concepts. Example: **Kingdom Monera** → historical Whittaker
  kingdom + modern **Bacteria** and **Archaea** (Woese), so both the original sources and the
  papers that replaced them are found. For an obsolete term, one result slot is reserved for a
  historical or field-defining source when one was found, so both sides of the story appear.
- Searches **seven trusted databases**: OpenAlex, **Europe PMC** (covers PMC), Semantic
  Scholar, Crossref, PubMed, **DOAJ** (vetted open-access journals) and **CORE**. Normal
  searches give the fast providers ~6 seconds and treat CORE as best-effort (~4 seconds), so a
  cold search usually finishes in **roughly 6–15 seconds** depending on provider latency. Turn
  on **Deep search** to give slow repositories such as CORE up to ~20 seconds.
- Merges duplicate papers (by DOI, then title) and keeps the best fields from each source.
- Ranks results with a transparent, **IDF-weighted** score so a famous but off-topic paper
  cannot beat the paper you actually need:
  `50% relevance + 33% citations + 7% recency + 5% review/textbook bonus + 5% foundational-paper bonus`.
  Missing citation counts are **backfilled from OpenAlex**, so landmark (highly cited) papers
  rise to the top. A **scope/centrality multiplier** keeps narrow applied, clinical, plant or
  database papers below the broad core literature for taxonomy-style questions, without
  penalising focused plant/clinical searches.
- **Precision-first relevance gate** — only the _distinctive_ words in your query decide the
  match (generic words like "characteristics" or "development" are down-weighted). A source is
  **CORE** only if its **title or abstract** directly addresses the main concept, or covers at
  least two concepts from the plan. Subject metadata alone is never enough, and generic matches
  such as "kingdom" or "nomenclature" cannot carry a result on their own. Each card shows
  **"Matched on: …"** so you can see _why_ it ranked. **Best match** (default) requires the
  main concept or two concepts; **More results** accepts any concept in the plan for broad or
  exploratory topics.
- **No padding.** If only two strong, distinct sources exist, you get two — not a page filled
  with weak matches. A small centered `:(` panel says so and offers a one-click broader search;
  the gate never falls back to gated-out papers, and it is not relaxed to hit a minimum count.
- **Downranks administrative material and meeting reports.** Ballots, committee announcements,
  editorials, errata, retraction notices, rule-emendation notices and meeting/conference reports
  are penalised and capped unless your topic is the rule-making process itself. No more than one
  source per narrow sub-story is shown (a proposal and its ballot count as one; duplicate
  Candidatus/GTDB naming papers collapse too), so every top result covers a different aspect.
- **Retraction and preprint safety.** Retracted papers are flagged with a clear warning and are
  hard-excluded in **Best match** mode. Preprints are labelled, and **Exclude preprints** is a
  one-click filter.
- **Clean, citation-ready metadata.** Provider quirks are normalised before a
  source is displayed or cited: journal abbreviations such as
  `Phytotherapy research : PTR` become `Phytotherapy Research`, shortened page
  ranges such as `8571-6` become `8571–8576`, and stray spaces before a title
  colon are removed. APA 7 journal articles without a page range include
  `Article [number]` after the volume and issue, e.g. `Journal, 12(3), Article e12345.`
- **Your last search is remembered** — switching to the Library and back (or refreshing) keeps
  your results, query and filters.
- **Stale searches cannot overwrite newer ones.** Starting a second search aborts the first
  request (and its background note call), and the browser has a 30-second timeout.
- **20 results at a time.** The first 20 render immediately and more load as you scroll, up to
  the 100 strongest distinct matches. The old **Max sources** control is gone.
- **Recent and popular searches.** The last five successful searches are stored privately in
  this browser; tap a chip to fill the query and run it immediately. A curated cross-domain
  popular row is always available, with one-click **Clear** for recents.
- **English-only by default** (toggle in **Filters**) — scholarly databases are multilingual.
- **Filters** contains free-to-read only, reviews/meta-analyses only, exclude preprints, and
  English sources only. **Best match / More results** and the **Deep search** on/off toggle sit
  next to the search button, not inside Filters. Resetting filters leaves those two choices
  alone.
- Shows title, authors, year, journal, citations, abstract, link and a **credibility checklist**.
- Writes **APA 7, MLA 9 and Chicago** citations, switchable with copy buttons. Citations prefer
  structured family/given names from Crossref, PubMed, Europe PMC and ORCID metadata, preserve
  accents, hyphens, particles and suffixes, and never rebuild a name from flat display text when
  structured fields exist. If providers disagree or a flat name is unsafe, every style is
  prefixed with **`[NEEDS CHECKING: author names]`** and the source card shows the same warning.
- Adds an **AI relevance note** to the top results. Cards appear immediately with a clear
  heuristic note; the top few are upgraded in the background through a separate notes request,
  so search never waits on the AI.
- Saves sources to your **Library** (the sidebar's **My Library (RRL)** page) with notes and tags.
- Exports the **current result set** directly as **CSV, BibTeX or an APA reference list**, and
  your saved Library as **BibTeX, .txt, .csv and .docx** (or copy every APA citation at once).
- **Find related sources** using a paper's references, its citing papers, and OpenAlex recommendations.

> **Why not Google Scholar / JSTOR / BASE?** Google Scholar and JSTOR have no public API, and
> BASE requires registered IP access, so they cannot be searched directly. Their journal content
> is largely reachable through OpenAlex, Crossref, Europe PMC/PMC, DOAJ and CORE, which is what
> this module uses.

## What Module 2 does

- **Paste anything, or upload a PDF.** An abstract, one section, or the full article works.
  PDFs are read page by page (up to 15 MB and 60 pages), and scanned image-only PDFs get a
  clear message instead of a fake summary.
- **Structured summary.** Every summary has a one-sentence **TL;DR**, then **key points,
  methods, findings and limitations** as short bullets you can actually study from.
- **Plain-English writing.** With AI available, the summary is rewritten in simple language
  instead of copied jargon. Without AI, a deterministic extractive summary is built offline.
- **Verbatim quote finder.** Quotes are chosen from the real sentences in your source. For
  PDFs each quote keeps its **page number**, ready to drop into an RRL. The AI can only pick
  **sentence numbers**, so it cannot invent a quote that is not in the paper.
- **Never depends on AI.** If the online AI is busy or no key is configured, the offline
  summarizer still returns methods, findings, limitations and quotes. The badge tells you
  whether you are looking at an **AI summary** or an **Offline summary**.
- **Save straight into My Library.** Add optional title/authors/year/journal/DOI details and
  the summary becomes a citable library entry, with the summary stored in its notes. If the
  paper is already in your library, the summary is appended to that saved source instead of
  creating a duplicate.
- **From search results to summary in one click.** Every Module 1 result with an abstract has a
  **Summarize** button that carries its abstract and citation details across, and links back to
  the saved source when there is one.
- **Copy or download.** Copy the whole summary, copy an individual quote, or download a plain
  `.txt` copy.

> **PDF tip:** if the PDF is a scan or a photo export, the words are images rather than text.
> Run OCR first (or paste the text) — the summarizer only quotes text it can actually read.

## Prerequisites

- **Python 3.11+** (tested on 3.14)
- **Node.js 20+** (tested on 24)
- VS Code (recommended) — the whole project is VS Code friendly.

## Setup (Windows)

```powershell
# From the repository root
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

This creates the Python virtualenv, installs backend + frontend dependencies, and copies
`.env.example` to `.env`. Then start everything:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

- Web app: <http://localhost:5173>
- API docs: <http://localhost:8000/docs>

### Manual run (two terminals)

```powershell
# Terminal 1 — backend
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — frontend
cd frontend
npm run dev
```

## Open the app on your phone

1. Keep both servers running on your PC.
2. Find your PC's IP address: `ipconfig` (look for IPv4 — yours may differ from the example).
3. On your phone (same Wi-Fi) open `http://<your-PC-IPv4>:5173`, for example `http://192.168.1.20:5173`.
4. Allow Python/Node through the Windows firewall if prompted (Private networks).
5. Use "Add to Home screen" — the PWA installs and runs full-screen, not desktop mode.

The frontend automatically calls the API on the **same host** at port `8000`, so no
configuration is needed for LAN access. Override it with `frontend/.env` → `VITE_API_URL`.

## Share it with other people (optional)

Local and LAN use needs no setup. To serve the whole app from **one URL**, build the
frontend and run the API as a single process:

```powershell
cd frontend
npm ci
npm run build
cd ..\backend
$env:SITE_PASSWORD = "choose-a-code"   # one shared access code
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>. FastAPI serves the built app **and** the API from the same
origin, so there is no CORS or `VITE_API_URL` to configure.

- **`SITE_PASSWORD`** gates every API route behind one access code. Visitors unlock once
  and stay signed in for 30 days (`SESSION_TTL_SECONDS`). Leave it empty for local/LAN use.
  Changing the password invalidates every existing session.
- **Inbound rate limits** (per client IP, per minute) protect the free scholarly APIs:
  120 requests overall, 20 searches, 20 summaries and 8 login attempts. Adjust them with
  the `RATE_LIMIT_*` variables.
- `/api/health` stays public so uptime and keep-alive checks work.
- For a shared deployment, point `DATABASE_PATH` at a separate database so visitors never
  write to your personal library.

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for a step-by-step **$0** Oracle Cloud Always Free
setup with HTTPS, a persistent library, automatic restarts and one-command updates.

## Free API keys (optional but recommended)

Copy `.env.example` to `.env` (the setup script already does this) and fill in what you have:

| Variable                   | Where to get it                               | Effect                                       |
| -------------------------- | --------------------------------------------- | -------------------------------------------- |
| `CONTACT_EMAIL`            | your email address                            | Enables OpenAlex/Crossref/NCBI "polite pool" |
| `OPENALEX_API_KEY`         | <https://openalex.org/settings/api> (free)    | Removes the shared anonymous budget          |
| `SEMANTIC_SCHOLAR_API_KEY` | <https://www.semanticscholar.org/product/api> | Fixes the "rate-limiting us" warning         |
| `NCBI_API_KEY`             | <https://account.ncbi.nlm.nih.gov/settings/>  | PubMed: 3 → 10 requests/second               |
| `CORE_API_KEY`             | <https://core.ac.uk/services/api>             | Enables the CORE source                      |
| `LLM_API_KEY`              | OpenRouter / Groq free tier / local Ollama    | Fast, reliable AI (topic + concepts + notes) |
| `CONCEPT_SEARCH_MAX_QUERIES` | optional (default `5`)                      | Number of modern/historical/concept searches |
| `CONCEPT_SEARCH_EXTRA_RESULTS` | optional (default `12`)                   | Results per provider for extra searches      |
| `SEARCH_PROVIDER_TIMEOUT_SECONDS` | optional (default `6`)                  | Per-provider deadline for normal searches    |
| `SEARCH_CORE_TIMEOUT_SECONDS` | optional (default `4`)                      | Best-effort CORE deadline (normal search)    |
| `SEARCH_DEEP_PROVIDER_TIMEOUT_SECONDS` | optional (default `20`)             | Deadline when **Deep search** is ticked      |
| `CITATION_BACKFILL_TIMEOUT_SECONDS` | optional (default `2`)                | Max wait for OpenAlex citation backfill      |
| `LLM_NOTE_TIMEOUT_SECONDS` | optional (default `15`)                    | Per-card AI note budget after results render |
| `LLM_NOTES_API_BUDGET_SECONDS` | optional (default `18`)                | Total budget for the lazy post-search notes  |

Nothing is required to start. Semantic Scholar's **anonymous** tier allows only about one
request per second, so without a key it may occasionally rate-limit and show a brief
"Heads up" notice; results from the other six sources are always shown. Adding the **free**
`SEMANTIC_SCHOLAR_API_KEY` removes that notice entirely.

### How the AI works (and its limits)

- **With no key** the app uses a free, no-signup AI endpoint for the topic rewrite, the concept
  plan and the relevance notes. It works, but it is **shared per network and rate-limited**:
  if it gets busy the app silently falls back to the offline heuristic and **backs off for a
  while** so searches stay fast. The sidebar shows **AI: online (free)** / **AI: offline**.
- **AI notes are lazy.** Search results render immediately with heuristic notes. The browser
  then requests an upgrade for the top three cards; that request has its own longer budget and
  is cancelled automatically if you start another search.
- **The offline concept plan never invents history.** It uses a small curated knowledge base
  for common school terms (Monera, Protista, binomial nomenclature, five-kingdom and
  three-domain classification, blue-green algae) and otherwise only expands the words in the
  topic plus the synonym map. Historical claims come from the curated entries, not guesses.
- **With a free key** (OpenRouter free models or Groq's free tier) you get consistent AI and
  upgraded notes. This is the recommended option for daily use.
- Either way, searching, ranking, citations, the library and exports **never depend on the AI**.

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Covers concept expansion, the title/abstract CORE gate, administrative and meeting-report
downranking, sub-story diversity (including Candidatus/GTDB), scope scoring, retraction and
preprint safety, provider timeouts, lazy notes, result exports, de-duplication, ranking,
filters, credibility rules, APA/MLA/Chicago formatting (including `Article [number]`), BibTeX
and CSV export, PDF text extraction, page-numbered quotes, offline summaries, AI JSON/quote
validation, and saving summaries into the library — all offline, no network needed.

```powershell
cd frontend
npm run typecheck
npm run build
```

## Project structure

```
Scholaris/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                     FastAPI app, CORS, router mounting
│  │  ├─ config.py                   .env-driven settings
│  │  ├─ core/                       cache, rate limiting, HTTP retries, LLM client
│  │  ├─ modules/research/           Module 1
│  │  │  ├─ router.py                HTTP endpoints
│  │  │  ├─ schemas.py               request/response models
│  │  │  ├─ models.py                provider-neutral SourceRecord
│  │  │  └─ services/
│  │  │     ├─ openalex.py  europepmc.py  semantic_scholar.py  crossref.py
│  │  │     ├─ pubmed.py  doaj.py  core.py          (source adapters)
│  │  │     ├─ interpret.py                         (question/brief → topic)
│  │  │     ├─ concepts.py                          (historical/current concept plan)
│  │  │     ├─ merge.py  ranking.py  synonyms.py  citations.py  notes.py
│  │  │     ├─ presenter.py  library.py  related.py  search.py
│  │  │     └─ text.py  (shared normalisation helpers)
│  │  └─ modules/summarize/          Module 2
│  │     ├─ router.py                text, PDF and save endpoints
│  │     ├─ schemas.py               summary request/response models
│  │     └─ services/
│  │        ├─ extract.py            text cleaning, sentence split, PDF pages
│  │        ├─ summarize.py          offline + AI summary, verbatim quotes
│  │        └─ save.py               summary → My Library notes
│  ├─ tests/                         offline unit tests
│  └─ data/                          SQLite library (git-ignored)
├─ frontend/
│  ├─ src/
│  │  ├─ api/                        typed API client
│  │  ├─ components/                 layout, icons, placeholders
│  │  ├─ hooks/                      theme
│  │  ├─ modules/research/           search page, forms, source card, citations
│  │  ├─ modules/summarize/          paste/PDF page, summary cards, quotes
│  │  └─ modules/library/            shared library state + My Library (RRL) page
│  ├─ public/                        icons + manifest assets
│  └─ vite.config.ts                 PWA configuration
├─ desktop/                          Tauri wrapper (added at packaging step)
├─ scripts/                          setup.ps1, dev.ps1
├─ .env.example
└─ README.md
```

## VS Code extensions

**Always useful**

- Python (Microsoft) + Pylance
- ESLint + Prettier
- SQLite Viewer (inspect `backend/data/library.sqlite3`)

**Modules 1 & 2 specifically**

- REST Client — run the sample requests in `backend/tests` docs or the `/docs` page
- GitLens (optional)

To debug the backend in VS Code, select the Python interpreter at
`backend\.venv\Scripts\python.exe` (Ctrl+Shift+P → "Python: Select Interpreter").

## Troubleshooting

| Symptom                      | Fix                                                                                                                                        |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| "API offline" in the sidebar | Start the backend; check <http://localhost:8000/api/health>                                                                                |
| Where do saved sources go?   | Sidebar → **My Library (RRL)** (also the Library button on the search page)                                                                |
| Results look off-topic       | Add a more specific word (organism, method or place); the app warns when nothing matches well. AI rewriting (below) fixes casual questions |
| Search feels slow            | Leave **Deep search** off; normal searches treat CORE as best-effort. Tick it only when you need repository coverage |
| AI note says "(quick)"     | The shared free AI hit its limit; the quick note is still usable. Add a free `LLM_API_KEY` for reliable AI upgrades |
| Semantic Scholar warning     | Anonymous limit (~1 req/s) — add the free `SEMANTIC_SCHOLAR_API_KEY`; it will not be remembered between searches                                                         |
| Non-English results appear   | Keep **English sources only** ticked (**Filters**); turn it off to include other languages                                                |
| No results at all            | Broaden the wording or turn off an option                                                                                                  |
| Summary says "Offline"       | The free AI is busy or no key is set; the offline summary is still real. Add a free `LLM_API_KEY` for written summaries                    |
| PDF has "no selectable text" | It is a scan/image PDF — run OCR first or paste the text; the summarizer only quotes text it can read                                      |
| Save summary button is grey  | The summary is already saved; open **My Library** to read it, or hit **Start over** to summarize another source                          |
| Phone can't connect          | Same Wi-Fi + allow Python/Node through the firewall                                                                                        |
| OpenAlex returns nothing     | Add a free `OPENALEX_API_KEY` (anonymous budget is shared per network)                                                                     |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and the secret-handling
rules. Never commit `.env` files or saved library databases.

## License

MIT — see [LICENSE](LICENSE).

## Next step

Run Module 1, try a search, save a source and export the bibliography. Then open **Source
Summarizer**, paste an abstract, and save the summary into My Library. When both work for you,
say **“next”** to build **Module 3 — Pre-Calculus & Physics**.
