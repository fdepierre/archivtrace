# ArchivTrace

**Citation-first documentary research assistant** — collect, analyse, and synthesize digital archives with mandatory verbatim sources.

> **Languages:** [English](README.md) · [Français](README-FR.md)

## Introduction

### Who is this tool for?

This tool is for **anyone** who wants to dig into a topic they care about — genealogy, local history, a neighborhood, a person, an event — using **digital sources** (historical newspapers, online archival collections, institutional catalogs…).

You can be a **complete beginner** with computers: you do not need to be a developer or a professional researcher. You only need to know how to open a **terminal** (command prompt) and copy-paste a few commands. Historians, archivists, and documentarians will also find a collection assistant here; curious readers and enthusiasts get a way to go further than simply browsing an archives website.

### What problem does it solve?

When researching a topic that interests you — for example *“Oradour in my region”*, or an ancestor’s name in the local press — you usually have to:

1. query several archives sites one by one;
2. open viewers, download PDFs;
3. read dozens of pages to spot useful passages;
4. note by hand what catches your attention;
5. reassemble everything before writing up what you discovered.

This tool **automates collection and the first analysis**: you give a **keyword**, it searches for documents, extracts text, finds relevant passages, and — if you want — has the content analyzed by an **LLM**. By default that is a **local** model via [Ollama](https://ollama.com) on your machine. You can also configure cloud providers (`openai`, `openrouter`, `perplexity`) in `config.json` / `--llm`; in that case prompts are sent to those APIs.

### What you get in practice

At the end, you have **structured text files** (Markdown format, `.md` extension) that you can open with any text editor, Visual Studio Code, or a notes app. These files serve as both:

- a **research notebook** (record of what was found, where, and how);
- **raw material** for writing a text: article, blog post, personal note, presentation…;
- **context** to give to an LLM (local or online) by saying: *“Write a text from this dossier.”*

Three kinds of documents are produced:

| File | Role |
|---|---|
| `work/research/…_collecte.md` | Everything that was found: sources, excerpts, analyses |
| `work/synthesys/…_synthese.md` | Overview: facts, chronology, gaps |
| `work/synthesys/…_contexte.md` | Dossier ready for writing a text (article, note, post…) |

### What you need (summary)

| Item | What it is for | Where to get it |
|---|---|---|
| **Python 3.11+** | Runs the tool | [python.org](https://www.python.org/downloads/) |
| **Ollama** | Local AI for analysis and synthesis | [ollama.com](https://ollama.com) |
| **This repository** | The program itself | Directory of your choice (e.g. `archivtrace`) |
| **An Internet connection** | To query archives sites | — |

> **Useful vocabulary**
> - **Markdown (`.md`)**: simple text format, readable as-is, with headings and lists.
> - **LLM / model**: generative AI program. By default two local Ollama models are used — `gemma4:26b` for per-document extraction, `qwen3.5` for long synthesis (see Configuration).
> - **Terminal**: window where you type commands (PowerShell on Windows, bash on Linux/WSL).
> - **Keyword / query**: the term you search for, e.g. `valmontagne`.

### Founding principle

**Markdown is the sole business output** of this tool: no Excel spreadsheet, no database to administer. Each step produces a structured document that is readable again and reusable.

---

## Step-by-step installation

Installation is done **once** on your machine. Allow about half an hour the first time (AI model download included).

**How to read this guide:** at each step, find the column that matches **your** environment and follow only that one.

| Environment | When to use it | Terminal to open |
|---|---|---|
| **Windows** | Windows PC, without WSL | **PowerShell** (Start menu → type “PowerShell”) |
| **Linux** | Native Linux PC or server (Ubuntu, Debian…) | **Terminal** (`Ctrl+Alt+T` on Ubuntu) |
| **WSL** | Windows, but you prefer Linux commands | **Ubuntu** (Start menu, after enabling WSL) |

> What is **WSL**? It is **Linux built into Windows**. Files on your C: drive are accessible from WSL under `/mnt/c/…`. If you hesitate between Windows and WSL on a Windows PC, choose **Windows** (simpler) or **WSL** if you are comfortable with Linux.

---

### Step 0 — Create the project directory

Create a folder to hold the program, for example `archivtrace` (copy from a USB drive, download, Git clone…).

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Where to create the folder | E.g. `C:\Users\YourName\archivtrace` | E.g. `~/archivtrace` | E.g. `/mnt/c/Users/YourName/archivtrace` (on the Windows disk) |
| Open a terminal **in** this folder | Explorer → right-click the folder → “Open in Terminal”, or `cd C:\Users\...\archivtrace` | `cd ~/archivtrace` | `cd /mnt/c/Users/YourName/archivtrace` |
| Verify the files are there | `dir` — you should see `collecte.py`, `README.md`, `README-FR.md`, `requirements.txt` | `ls` — same | `ls` — same |

---

### Step 1 — Install Python 3.11 or newer

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| How to install | Installer from [python.org/downloads](https://www.python.org/downloads/) — **check “Add Python to PATH”** | `sudo apt update` then `sudo apt install python3 python3-pip python3-venv` | **First** enable WSL (see box below), **then** the same commands as Linux |
| Verify | `python --version` | `python3 --version` | `python3 --version` |
| Expected result | `Python 3.11.x` or `3.12.x` | same | same |

**Windows (PowerShell) — verification:**
```powershell
python --version
```

**Linux and WSL — install and verify:**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
python3 --version
```

> **WSL — first-time setup (once only, before step 1)**  
> In PowerShell **as administrator** on Windows: `wsl --install`  
> Restart the PC, then open **Ubuntu** from the Start menu. The following steps are done in that Ubuntu terminal.

---

### Step 2 — Install Ollama and the AI models

Ollama runs artificial intelligence **on your machine**. Recommended downloads (~24 GB total once):

| Model | Role | Approx. size |
|---|---|---|
| `gemma4:26b` | Per-document claim extraction (JSON + citations) | ~17 GB |
| `qwen3.5` | Long-context synthesis | ~6.6 GB |
| `llama3.2` (optional) | Fallback if a task model is missing | ~2 GB |

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Install Ollama | Installer from [ollama.com/download](https://ollama.com/download) — tray icon once launched | `curl -fsSL https://ollama.com/install.sh \| sh` | **Option A (recommended)**: install Ollama on **Windows** (installer) — reachable from WSL via `localhost` · **Option B**: Linux script in the Ubuntu terminal |
| Download models | `ollama pull gemma4:26b` then `ollama pull qwen3.5` | same | same |
| Verify | `ollama list` — both models should appear | same | same |

**Common commands (Windows PowerShell, Linux, or WSL):**
```bash
ollama pull gemma4:26b
ollama pull qwen3.5
ollama pull llama3.2   # optional fallback
ollama list
```

> **WSL + Ollama on Windows (option A)**: leave `config.json` with `"host": "http://localhost:11434"` inside the `llm` block (or flat `"ollama_host"`) — this works from WSL with no extra configuration.

---

### Step 3 — Install the program (Python environment)

Go to the project directory (step 0), then create a **virtual environment** (`.venv`) and install the dependencies.

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Go to the project | `cd C:\path\to\archivtrace` | `cd ~/path/to/archivtrace` | `cd /mnt/c/Users/YourName/.../archivtrace` |
| Create the environment | `python -m venv .venv` | `python3 -m venv .venv` | `python3 -m venv .venv` |
| Activate the environment | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` | `source .venv/bin/activate` |
| Install packages | `pip install -r requirements.txt` | same | same |
| Shared Ollama client | `pip install -e ..\shared\ollama_shared` | `pip install -e ../shared/ollama_shared` | `pip install -e ../shared/ollama_shared` |
| Sign it worked | the prompt shows `(.venv)` at the start of the line | same | same |

**Windows (PowerShell):**
```powershell
cd C:\path\to\archivtrace
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e ..\shared\ollama_shared
```

**Linux:**
```bash
cd ~/path/to/archivtrace
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ../shared/ollama_shared
```

**WSL (Ubuntu terminal):**
```bash
cd /mnt/c/Users/YourName/path/to/archivtrace
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ../shared/ollama_shared
```

> **Windows — if PowerShell refuses to activate the venv** (“script execution is disabled”), run once:  
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

---

### Step 4 — Verify everything works

Test without actually downloading PDFs (`--dry-run`).

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Activate the environment | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` | `source .venv/bin/activate` |
| Run the test | `python collecte.py --query "valmontagne" --connector numelyo --dry-run --max-results 2` | same (`python3` if `python` is missing) | same |
| Expected result | a file appears in `work\research\` | a file appears in `work/research/` | same |

---

### First use — the 4-command cycle

**Every time** you open a new terminal, reactivate the environment first:

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Activate the environment | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` | `source .venv/bin/activate` |

Then run (identical on all three environments):

```bash
# 1. Collect documents for the keyword (one file per site)
python collecte.py --query "valmontagne" --connector numelyo --max-results 5

# 2. Semantic analysis by AI, document by document — slower
python analyse.py --input work/research/2026-06-28_valmontagne_numelyo_collecte.md --only-matches

# 3. Multi-site corpus synthesis (merges all connectors for the keyword)
python synthesize.py --query "valmontagne"

# 4. Dossier for writing your text
python synthesize.py --query "valmontagne" --mode contexte
```

Results are in the **`work/research/`** and **`work/synthesys/`** folders. Open the `.md` files with your preferred editor.

> **Tip**: always start with `--dry-run` or `--max-results 2` for a quick trial without downloading too many PDFs.

### Advanced options (optional)

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Optional OCR (**PaddleOCR**) | `pip install paddlepaddle paddleocr` | same | same |
| Usage example | `python analyse.py --input work/research/…_collecte.md --only-matches --enable-ocr` | same | same |

---

## Table of contents

**Getting started**
- [Introduction](#introduction)
- [Step-by-step installation](#step-by-step-installation) (Windows, Linux, WSL)

**Technical documentation**

1. [Pipeline overview](#pipeline-overview)
2. [Project architecture](#project-architecture)
3. [Data models](#data-models)
4. [The collection pipeline (step by step)](#the-collection-pipeline-step-by-step)
5. [Connectors (sources)](#connectors-sources)
6. [Download strategies](#download-strategies)
7. [Text extraction and OCR](#text-extraction-and-ocr)
8. [Keyword matching (mechanical)](#keyword-matching-mechanical)
9. [Idea extraction via LLM](#idea-extraction-via-llm)
10. [Synthesis and writing context](#synthesis-and-writing-context)
11. [Markdown files produced](#markdown-files-produced)
12. [Configuration](#configuration)
13. [Installation reference (summary)](#installation-reference-summary)
14. [Usage — CLI](#usage--cli)
15. [LLM gateway and shared Ollama package](#llm-gateway-and-shared-ollama-package)
16. [Tests](#tests)
17. [Adding a new source](#adding-a-new-source)
18. [Complete example](#complete-example)

---

## Pipeline overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 1 — COLLECTION                        collecte.py                     │
│                                                                         │
│  keyword ──► connector ──► HTML/API search on the archives site        │
│                    │                                                    │
│                    ▼                                                    │
│              candidates (titles, URLs, IDs)                             │
│                    │                                                    │
│                    ▼                                                    │
│              download strategy ──► local PDF (work/downloads/)               │
│                    │                                                    │
│                    ▼                                                    │
│              text extraction (native PDF or PaddleOCR)                  │
│                    │                                                    │
│                    └──► mechanical matcher (excerpts around the keyword)│
│                    │                                                    │
│                    ▼                                                    │
│         work/research/{date}_{topic}_{connector}_collecte.md                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 2 — ANALYSIS                          analyse.py                  │
│                                                                         │
│  Re-reads Markdown + local PDFs ──► LLM task « extraction »             │
│  (default model: gemma4:26b — JSON claims + verbatim citations)         │
│                    │                                                    │
│                    ▼                                                    │
│         work/research/{date}_{topic}_{connector}_collecte.md  (enriched)    │
│         (section « Idées extraites (LLM) » per source)                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 3 — SYNTHESIS                         synthesize.py               │
│                                                                         │
│  Re-reads collection Markdown ──► LLM task « synthesis »                │
│  (default model: qwen3.5 — long-context narrative + structured blocks)  │
│                    │                                                    │
│                    ▼                                                    │
│         work/synthesys/{date}_{topic}_synthese.md                             │
│         (research note: facts, chronology, sources, gaps)               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 4 — WRITING CONTEXT                   synthesize.py --mode contexte│
│                                                                         │
│  Same synthesis model family ──► structured writing dossier             │
│                    │                                                    │
│                    ▼                                                    │
│         work/synthesys/{date}_{topic}_contexte.md                             │
│         (ready to feed an LLM or a human to write the article)         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Two LLM tasks (same gateway, different models):**

| When | Command | Module | Task role | Default Ollama model |
|---|---|---|---|---|
| After collection | `analyse.py` | `llm_idea_extractor.py` | `extraction` | `gemma4:26b` |
| After analysis | `synthesize.py` | `synthesizer.py` | `synthesis` | `qwen3.5` |

Routing lives in `pipeline/llm_task_models.py` (`get_model_for_task`). One call path (`LlmGateway`); model id, thinking flag, and fallback are chosen per task. Missing local models warn and fall back to `llm.fallback_model` (default `llama3.2`) instead of crashing. Details: [Configuration — Multi-model Ollama](#multi-model-ollama-task-routing).

The mechanical matcher (`keyword_matcher.py`) remains useful: it quickly locates pages and passages containing the keyword, and serves as localization hints for the LLM.

### How this README describes architecture (vs code)

| Layer | What it documents | What it does **not** duplicate |
|---|---|---|
| **This README** | Stages, contracts (citation-first), config, CLI, which module owns which role | Function signatures, parameter lists, internal algorithms |
| **Module / function docstrings** | *How* a component works | Product positioning / install guides |
| **`AGENTS.md` + `.cursor/skills/`** | Conventions for agents (paths, venv, OCR, LLM entry points) | End-user tutorials |

Prefer a **flow + responsibility table + config contract**. When behaviour changes, update the flow/table here and keep implementation detail in the Python docstrings.

---

## Project architecture

```
archivtrace/
│
├── work/                        # Non-code artefacts
│   ├── research/                # Collection + analysis Markdown
│   ├── downloads/               # PDF / image cache
│   └── synthesys/               # Syntheses / contexts
│
├── collecte.py                  # Collection CLI — contains no business logic
├── analyse.py                   # Per-document LLM analysis CLI (task: extraction)
├── synthesize.py                # Synthesis / writing-context CLI (task: synthesis)
├── verify.py                    # Deprecated — NLI/CoVe via synthesize + config.json
├── config.py                    # Typed Config object (dataclass)
├── config.json                  # LLM / pipeline settings (JSONC; nested llm block)
├── models.py                    # All data models (dataclasses + enums)
│
├── connectors/                  # One archives source = one package
│   ├── __init__.py              # REGISTRY + build_connector()
│   ├── base.py                  # Abstract Connector class
│   ├── numelyo/                 # Numelyo / BM Lyon
│   │   ├── connector.py
│   │   └── parsing.py
│   ├── archives_rhone/          # Archives du Rhône
│   │   ├── connector.py
│   │   └── parsing.py
│   ├── archives_map/            # MPP / Archiv'MH (Ligeo)
│   │   ├── connector.py
│   │   └── parsing.py
│   └── catalog_html/            # Generic HTML catalog template
│       └── connector.py
│
├── strategies/                  # How to download a resolved document
│   ├── base.py                  # Abstract DownloadStrategy class
│   ├── direct_download.py       # Direct URL to a file
│   ├── viewer_to_pdf.py         # Viewer → PDF (Numelyo: ISSUE_PDF)
│   ├── session_cookie.py        # PHPSESSID session then download
│   ├── html_scrape.py           # HTML page → link to the file
│   ├── api_query.py             # JSON/REST API
│   └── browser_automation.py    # Playwright (last resort, optional)
│
├── pipeline/                    # Business core — source-independent
│   ├── collector.py             # Orchestrator: search → … → CollectionRun
│   ├── text_extractor.py        # PDF → page-by-page text
│   ├── ocr_extractor.py         # OCR fallback (PaddleOCR, optional)
│   ├── keyword_matcher.py       # Mechanical keyword + context spotting
│   ├── llm_idea_extractor.py    # Per-document semantic analysis (extraction)
│   ├── llm_gateway.py           # Single LLM entry point (Ollama + OpenAI-compatible APIs)
│   ├── llm_task_models.py       # Task → model / thinking / fallback
│   ├── llm_validation_stats.py  # Per-model JSON validation counters
│   ├── llm_call_log.py          # Rotating JSONL call log (cost telemetry)
│   ├── llm_client.py            # Re-exports from llm_gateway (compat)
│   ├── prompts.py               # Loads versioned prompts from prompts/
│   ├── prompt_loader.py         # Prompt file loader (version + XML sections)
│   ├── prompt_schemas.py        # Pydantic validation of LLM JSON outputs
│   ├── grounded_claims.py       # Deterministic gate: confirmed claims → synthesis
│   ├── source_classifier.py     # Probative vs non-probative source classify
│   ├── source_criticism.py      # External criticism priors (Gottschalk-inspired)
│   ├── synthesis_structure.py   # Catalog / chronology / theme structures
│   ├── nli_verifier.py          # Optional NLI check on established facts
│   ├── cove_verifier.py         # Optional Chain-of-Verification
│   ├── verification_pipeline.py # Combines NLI + CoVe
│   ├── analyse_policy.py        # Resume decision / analysis filters
│   ├── markdown_format.py       # Canonical Markdown format (markers)
│   ├── markdown_reporter.py     # CollectionRun → collection Markdown
│   ├── markdown_patcher.py      # Inject / replace LLM sections
│   ├── markdown_reader.py       # Collection Markdown → re-read structure
│   ├── collection_analyzer.py   # Analysis loop (OCR + LLM + persistence)
│   └── synthesizer.py           # Re-read collection → synthesis or context
│
├── prompts/                     # Versioned LLM prompts (XML-structured; latest = highest vN)
│   ├── analyze_document.v2.xml.txt
│   ├── synthesize_claims.v2.xml.txt
│   ├── classify_source.v1.xml.txt
│   └── article_context.v1.xml.txt
├── utils/
│   ├── http.py                  # HTTP client (timeout, delay, retries, UTF-8)
│   ├── strings.py               # Normalization, slug, keyword variants
│   ├── dates.py                 # run_id, timestamps
│   ├── files.py                 # Safe writes, paths
│   └── app_config.py            # config.json → Config (CLI > json > defaults)
│
├── tests/                       # Unit and offline integration tests
├── work/research/               # Business output: collection/analysis Markdown
├── work/downloads/              # Downloaded PDF cache (gitignored)
├── work/synthesys/              # Syntheses and contexts
├── queries.txt                  # Example multi-query file
├── requirements.txt
└── pyrightconfig.json           # ollama_shared package resolution for the linter
```

Shared external package (sibling):

```
../shared/ollama_shared/         # Factorized Ollama client (YouTube2Post, etc.)
```

### Separation of responsibilities

| Layer | Files | Responsibility | Knows the source? |
|---|---|---|---|
| **CLI** | `collecte.py`, `analyse.py`, `synthesize.py`, `verify.py` | Arguments, config, wiring | No |
| **Connector** | `connectors/*.py` | URLs, search, parsing, resolution | **Yes** |
| **Strategy** | `strategies/*.py` | Download a local file | Partially |
| **Pipeline** | `pipeline/*.py` | Orchestration, text, matching, LLM, Markdown | **No** |
| **Prompts** | `prompts/*.xml.txt` | Versioned LLM instructions (citation-first) | No |
| **Models** | `models.py` | Data contracts between components | No |
| **Utils** | `utils/*.py` | HTTP, strings, files, config | No |

**Consequence:** adding an archive = a new connector (+ optionally a strategy). The pipeline, reporter, and synthesis do not change.

**LLM consequence:** swapping models per task = edit `config.json` `llm.models` (or CLI/env). Call sites keep using `build_llm_gateway(..., task=…)` — no duplicated Ollama client code.

---

## Data models

All objects exchanged between components are defined in `models.py`.

### Document lifecycle

```
DocumentCandidate  →  ResolvedDocument  →  DownloadResult
       │                      │                    │
       └──────────────────────┴────────────────────┘
                              │
                              ▼
                    CollectedDocument
                    ( + ExtractedText
                      + KeywordMatch[]
                      + LlmExtraction? )
                              │
                              ▼
                       CollectionRun
                              │
                              ▼
                    Collection Markdown
```

### Main objects

| Class | Role |
|---|---|
| `DocumentCandidate` | Raw search result (title, URL, ID, collection) |
| `ResolvedDocument` | Candidate enriched with download/viewer URLs and chosen strategy |
| `DownloadResult` | Technical download result (local path, HTTP, error) |
| `ExtractedText` | Page-by-page extracted text (`ExtractedPage[]`) |
| `KeywordMatch` | Mechanical keyword occurrence + context + page |
| `LlmExtraction` | Ollama semantic analysis of a document (structured Markdown) |
| `CollectedDocument` | Fully processed document (unit of a Markdown section) |
| `CollectionRun` | Full result of a query (reporter input) |

### Statuses (`DocumentStatus`)

`found` → `resolved` → `downloaded` → `extracted` | `failed` | `ignored`

---

## The collection pipeline (step by step)

Implemented in `pipeline/collector.py`, orchestrated by `collecte.py`.

| # | Step | Module | Description |
|---|---|---|---|
| 1 | **Search** | `connector.search()` | HTTP query on the site, HTML parsing → list of `DocumentCandidate` |
| 2 | **Resolution** | `connector.resolve()` | Enriches each candidate (PDF URL, viewer, strategy) |
| 3 | **Download** | `connector.download()` → strategy | Local PDF in `work/downloads/{connector}/` |
| 4 | **Text extraction** | `TextExtractor` (+ `OcrExtractor`) | pymupdf → pdfplumber → pypdf; if `--enable-ocr` → **PaddleOCR** |
| 5 | **Mechanical matching** | `KeywordMatcher` | Keyword occurrences + context window + page number |
| 6 | **Scoring** | `relevance_score()` | Simple relevance score per document |
| 7 | **Report** | `MarkdownReporter` | `CollectionRun` → `.md` file |

**Next step (separate command):** `analyse.py` re-reads local PDFs and enriches the Markdown with an « Idées extraites (LLM) » section per source (`LlmIdeaExtractor`).

**Error handling:** no step breaks the pipeline. Download or OCR failure → recorded in the Markdown (technical notes), move on to the next document.

**Dry-run mode (`--dry-run`):** steps 1–2 executed, heavy download skipped, partial Markdown still produced.

---

## Connectors (sources)

A connector implements the contract in `connectors/base.py`:

```python
class Connector(ABC):
    def build_search_url(self, query: str) -> str: ...
    def search(self, query: str) -> list[DocumentCandidate]: ...
    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument: ...
    def build_strategies(self) -> list[DownloadStrategy]: ...
```

Registration in `connectors/__init__.py` → `REGISTRY`.

### Numelyo (`numelyo`) — main implementation

Site: [numelyo.bm-lyon.fr](https://numelyo.bm-lyon.fr) / [collections.bm-lyon.fr](https://collections.bm-lyon.fr)

| Action | Detail |
|---|---|
| Search | `GET …/list/?order_by=Relevance&cat=quick_filter&typedoc=all&search_keys[0]={query}&rows=5` |
| Pagination | Next pages via `list.php?…&pager_row=N` (5 results/page → e.g. 396 hits = 80 pages) |
| Types | Press (`collections.bm-lyon.fr`, PDF via `ISSUE_PDF`) and illustrations (`/f_view/…`, JPEG preview) |
| Parsing | Press IDs (`BML_01PER…`, `PER…`) and illustrations (`BML:…` → `SourceType.IMAGE`) |
| Press viewer | `collections.bm-lyon.fr/presseXIX/{ID}?pageOrder=N` |
| PDF | `collections.bm-lyon.fr/{ID}/ISSUE_PDF` |
| Press strategy | `ViewerToPdfStrategy`; illustrations → `DirectDownloadStrategy` |
| Limit | `--max-results` caps the number of documents processed; increase it to walk more pages |

### Archives du Rhône (`archives_rhone`)

Site: [archives.rhone.fr](https://archives.rhone.fr) — search example: [`/search/results?q=…&scope=all`](https://archives.rhone.fr/search/results?q=rochecardon&scope=all)

- Search HTML (`li.element-list`) → ARK notices (`/ark:/28729/…`)
- Download preference: `/media/<uuid>.pdf` when present, else still image `/images/<uuid>.jpg`
- Notices without digital media → HTML scrape of the record page
- Pagination: `&page=N` (1-based)

```bash
python collecte.py --query "sujet" --connector archives_rhone --max-results 20
python collecte.py --query "sujet" --connector archives_rhone --dry-run --max-results 5
```

### Médiathèque du patrimoine / Archiv'MH (`archives_map`)

Site: [archives-map.culture.gouv.fr](https://archives-map.culture.gouv.fr) (Ligeo Archives) — example: [`RECH_S=pontarlier`](https://archives-map.culture.gouv.fr/archive/resultats/simple/lineaire/FRAMAP_806827/n:19?RECH_S=pontarlier&type=simple)

- Simple search `RECH_S` → results faceted by inventory (`FRAMAP_*`)
- Notices: `/archive/fonds/FRAMAP_…/view:…`
- Digitized items: ARK viewer + IIP JPEG (`iipsrv.fcgi`, higher `HEI` for download)
- Catalog-only notices → HTML fiche download for text / keyword matching
- Pagination inside a facet: `/page:N`

```bash
python collecte.py --query "pontarlier" --connector archives_map --max-results 20
python collecte.py --query "pontarlier" --connector archives_map --dry-run --max-results 5
```

### Catalog HTML (`catalog_html`) — multi-source template

Generic connector for institutional sites with GET search + HTML link list.

```bash
python collecte.py --query "sujet" --connector catalog_html \
  --catalog-search-url "https://archives.example.org/search?q={query}" \
  --catalog-root "archives.example.org"
```

Test fixture: `tests/fixtures/catalog_results.html`.

---

## Download strategies

Each connector declares an **ordered** list. The first strategy that `supports(document)` is used.

| Strategy | File | Use case |
|---|---|---|
| `ViewerToPdfStrategy` | `viewer_to_pdf.py` | Paginated viewer → derived PDF URL (Numelyo) |
| `DirectDownloadStrategy` | `direct_download.py` | File directly reachable by URL |
| `SessionCookieStrategy` | `session_cookie.py` | Visit the viewer to obtain a cookie, then PDF |
| `HtmlScrapeStrategy` | `html_scrape.py` | HTML landing page containing the file link |
| `ApiQueryStrategy` | `api_query.py` | JSON API returning the URL or binary |
| `BrowserAutomationStrategy` | `browser_automation.py` | Headless Playwright (**last resort**) |

**Contract:** `download()` never raises an exception → always returns a `DownloadResult` (`success=False` + `error` on failure).

---

## Text extraction and OCR

### Native extraction (`pipeline/text_extractor.py`)

Attempt order: **pymupdf → pdfplumber → pypdf** (first installed backend that works).

Text is returned **page by page** (`ExtractedPage`) so excerpts can be located in the Markdown.

### OCR (`pipeline/ocr_extractor.py`, optional)

Single engine: **[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)** (`paddleocr` + `paddlepaddle` runtime), fully installable via `pip` — **no Tesseract** and no system binary.

Enabled with `--enable-ocr` / `enable_ocr` when the native text layer is missing or insufficient (`ocr_required`), including for **illustrations** (`.jpg`, `.png`, …).

```
PDF  : PyMuPDF (fitz) rasterizes each page (configurable DPI, default 200) → PaddleOCR
Image : PaddleOCR direct (predict() API 3.x, fallback ocr() 2.x)
```

| Detail | Behavior in code |
|---|---|
| Module | `pipeline/ocr_extractor.py` → class `OcrExtractor` |
| Dependencies | `paddlepaddle`, `paddleocr` (see `requirements.txt`) |
| CLI language | `--ocr-lang fra` (default) → PaddleOCR code `fr`; `eng`/`en` → `en` |
| Reported extractor | `ocr_paddle` (PDF) / `ocr_paddle_image` (illustration) |
| Windows CPU | initialized with `enable_mkldnn=False` (avoids a PaddlePaddle 3.3.x oneDNN/PIR bug) |
| First run | download of official models (~hundreds of MB, cache `~/.paddlex/`) |

```bash
pip install paddlepaddle paddleocr

# Collection or analysis with OCR
python collecte.py --query "sujet" --connector numelyo --enable-ocr --ocr-lang fra
python analyse.py --input work/research/…_collecte.md --only-matches --enable-ocr --ocr-lang fra
```

With `--enable-ocr`, sources previously marked « Ignoré » (images / scans without text) are **retried** automatically.

---

## Keyword matching (mechanical)

Module: `pipeline/keyword_matcher.py`

| Mode | CLI `--match-mode` | Behavior |
|---|---|---|
| `exact` | `exact` | Case-sensitive substring |
| `normalized` | `normalized` (default) | Case-, accent-, and whitespace-insensitive |
| `fuzzy` | `fuzzy` | Nearby token via `difflib` (OCR typos) |

For each occurrence: match text, before/after context (`--context-window`, default 160 chars), page number, match type, score.

These excerpts appear in the Markdown under **« Extraits liés au mot-clé »** and are passed to the LLM as localization hints.

---

## Idea extraction via LLM

Module: `pipeline/llm_idea_extractor.py`  
Command: **`analyse.py`** (separate step, after `collecte.py`).  
Default task model: **`gemma4:26b`** (`llm.models.extraction`) — thinking off for strict JSON.

All LLM traffic goes through **`pipeline.llm_gateway.LlmGateway`** (`build_llm_gateway(..., task="extraction")`).

### Prompts (versioned, citation-first)

Prompt text lives under **`prompts/`** (not hard-coded in Python). Each file has a
version header (`# version: N`) and XML sections (`<role>`, `<constraints>`,
`<output_format>`, `<examples>`, `<user_template>`).

| File | Task |
|---|---|
| `prompts/analyze_document.vN.xml.txt` | Per-document claims + mandatory verbatim citation |
| `prompts/synthesize_claims.vN.xml.txt` | Corpus synthesis from structured claims |
| `prompts/classify_source.vN.xml.txt` | Probative vs non-probative source |
| `prompts/article_context.vN.xml.txt` | Writing-context dossier |

**Rule:** no claim without an exact `citation_exacte` found in the supplied text.
Uncertainty must use statut `insuffisant` / `document_status: a_revoir_manuellement`
rather than guessing. Outputs are validated with **Pydantic**
(`pipeline/prompt_schemas.py`); invalid JSON → logged error and
« à revoir manuellement » (not silently inserted into synthesis).

To change behaviour: edit or add `prompts/<id>.vN.xml.txt`, bump `N`, then run:

```bash
pytest tests/test_prompt_grounding.py -q
```

### What the LLM does at this step

For **each document** whose PDF is available in `work/downloads/`:

1. Re-extracts text from the local PDF
2. Replays mechanical matching (same keyword and parameters as collection)
3. Selects relevant pages (those with matches + neighbors)
4. Sends a text sample (max `llm_max_chars`, default 12,000) to the **extraction** model
5. Requests **structured JSON claims** (citation + affirmation + confidence + status), then renders additive Markdown:

```markdown
## Idées et faits liés au sujet
## Passages citables
## Pertinence pour la recherche
## Limites de ce document
## Affirmations structurées (JSON)
```

6. Updates the **« Idées extraites (LLM) »** section in the collection Markdown

**Important:** this step is **slow** (several minutes per document with a large model). Use `--only-matches` to process only relevant sources.

```bash
python analyse.py --input work/research/2026-06-28_valmontagne_collecte.md --only-matches
```

---

## Synthesis and writing context

Module: `pipeline/synthesizer.py`  
CLI: `synthesize.py`  
Default task model: **`qwen3.5`** (`llm.models.synthesis`) — long context; thinking off by default (JSON fences).

Re-reads a collection Markdown (`markdown_reader.py`), filters grounded claims (`grounded_claims.py`), and calls the gateway with **`task="synthesis"`** to aggregate **the whole corpus**.

### Mode `synthese` (default)

Produces a **research note** from **confirmed grounded claims only**
(`statut=confirme_par_le_document`, non-empty citation, source usable as proof),
then applies **multi-source corroboration**: a fact enters **Faits établis** only if
at least **two independent sources** support the same claim family; otherwise it is
listed under **Hypothèses** with `corroboration_insuffisante`.

| Section | Content |
|---|---|
| **Faits établis et sourcés** | Only Pydantic-validated, multi-source facts with `[S:n]` anchors |
| **Chronologie sourcée** | Dated events, each with `[S:n]` |
| **Hypothèses et vérifications à mener** | Single-source claims, open questions — never established history |
| **Contrôle des références** | Counts `[S:n]` used vs catalog; external-criticism alerts on sources |

Optional post-checks:

- `--allow-single-source-facts` — disable the 2-source rule (debug / exploratory)
- NLI filter **on by default** (deterministic entailment; `--nli-llm` for LLM labels; `--no-nli` to disable)
- `--verify-cove` — Chain-of-Verification against the citation (extra LLM cost)
- NLI/CoVe: `synthesis.*` policies in `config.json` (applied by `synthesize.py`). `verify.py` remains available but is **deprecated**.

Related modules: `pipeline/corroboration_checker.py`, `pipeline/source_criticism.py`,
`pipeline/nli_verifier.py`, `pipeline/cove_verifier.py`, `pipeline/verification_pipeline.py`.
Extraction prompt v2 adds `poids_preuve`. Archival connectors start as `non_determine`
until external criticism upgrades (or downgrades) `classe_preuve`.

**qwen3.5 is never a source** — it only organises claims already proven by documents.
Invalid LLM output (`[0]`, unknown ids, missing `[S:n]`) is **rejected**: the Markdown
shows « Synthèse non validée » / a warning banner instead of unsourced narrative.

Offline / no LLM: corroborated claims are promoted deterministically (no invention).

File: `work/synthesys/{date}_{topic}_synthese.md` (cross-site by default)

Regression: `pytest tests/test_synthesis_grounding.py tests/test_historical_validation.py -q`

### Mode `contexte`

Produces a **writing dossier** to feed an LLM (or to write yourself):

- Subject sheet
- Retained documentary corpus
- Established facts (with sources)
- Passages to quote
- Possible narrative thread
- Gaps and caution
- Writing guidelines

File: `work/synthesys/{date}_{topic}_contexte.md`

---

## Markdown files produced

| File | Command | Content |
|---|---|---|
| `{date}_{topic}_{connector}_collecte.md` | `collecte.py` → `work/research/` | Full trace per site: metadata, each source, mechanical excerpts, LLM ideas, technical notes |
| `{date}_{topic}_synthese.md` | `synthesize.py --query` → `work/synthesys/` | Narrative synthesis merging all sites for the keyword (URLs kept) |
| `{date}_{topic}_contexte.md` | `synthesize.py --mode contexte` → `work/synthesys/` | Structured dossier for article writing |

### Structure of a collection Markdown (stable)

Each source (`## Source N — title`) contains:

```
### Identité          (URLs, ID, connector, strategy, status)
### Pertinence        (keyword, match count, score)
### Extraits liés au mot-clé     ← mechanical matcher
### Idées extraites (LLM)        ← Ollama analysis (via analyse.py)
### Localisation des extraits    (pages)
### Métadonnées documentaires
### Notes OCR / extraction
### Notes techniques             (HTTP, MIME, errors)
```

Global sections: Métadonnées, Résumé de collecte, Paramètres de recherche, Sources ignorées, Observations, Annexes techniques.

---

## Configuration

### Design rule — no claim without a verbatim citation

Every affirmation produced by analysis must rest on a `citation_exacte` copied
from the supplied document text. If the fact is missing or ambiguous, the model
must use statut `insuffisant` / `document_status: a_revoir_manuellement` rather
than inventing. This is a core project contract (enforced in prompts + Pydantic
validation), independent of which local model is configured.

### `config.py` — `Config` object

Typed container passed to all components. Main fields:

| Field | Default | Description |
|---|---|---|
| `output_dir` | `work/research` | Markdown folder |
| `download_dir` | `work/downloads` | PDF cache |
| `timeout` / `delay` | 30s / 1s | HTTP |
| `max_results` | 20 | Cap on documents processed |
| `dry_run` | false | Without heavy download |
| `match_mode` | `normalized` | Matching mode |
| `context_window` | 160 | Context characters around matches |
| `enable_ocr` | false | **PaddleOCR** fallback (`OcrExtractor`) |
| `ocr_lang` | `fra` | CLI language → mapped to PaddleOCR codes (`fra`→`fr`) |
| `ocr_dpi` | 200 | PDF rasterization DPI before OCR |
| `ollama_host` | `http://localhost:11434` | Ollama URL when `llm_provider=ollama` |
| `llm_provider` | `ollama` | `ollama` \| `openai` \| `openrouter` \| `perplexity` \| `none` |
| `llm_model_extraction` | `gemma4:26b` | Model for grounded claim extraction |
| `llm_model_synthesis` | `qwen3.5` | Model for long-context synthesis |
| `llm_fallback_model` | `llama3.2` | Used when the task model is not installed |
| `llm_thinking_extraction` | `false` | Ollama `think` for extraction (keep off for JSON) |
| `llm_thinking_synthesis` | `false` | Ollama `think` for synthesis (off by default — often skips JSON fences) |
| `llm_model` / `ollama_model` | `qwen3.5` | Legacy single-model fallback |
| `llm_api_key` | `null` | Prefer env `*_API_KEY` instead |
| `llm_max_chars` | 12000 | Max text sent to the LLM per document |
| `ollama_timeout` | 600 | Shared LLM generation timeout (s) |
| `llm_log_dir` | `work/logs/llm` | Rotating JSONL call logs |

### Multi-model Ollama (task routing)

Declare models per task in the nested `llm` block (preferred — same shape can
later feed an online service). Resolution goes through
`pipeline.llm_task_models.get_model_for_task(task)`:

| Task | Typical use | Default model | Thinking |
|---|---|---|---|
| `extraction` | `analyse.py` / claim JSON | `gemma4:26b` | off |
| `synthesis` | `synthesize.py` narrative | `qwen3.5` | off (set `true` to experiment) |
| `classification` | source class | same as extraction | off |

If a configured model is missing locally, the gateway warns and falls back to
`fallback_model` instead of crashing.



### Analyse / synthesis policies (`config.json`)

For daily use, prefer editing `config.json` over stacking CLI flags:

```jsonc
"analyse": { "auto_ocr": false, "two_pass_extraction": false },
"synthesis": {
  "facts_mode": "tiered",   // tiered | strict | all
  "verify_nli": true,
  "verify_cove": false,
  "nli_llm": false
}
```

Callable API (future UI): `pipeline.run_api.run_synthesize`.

### `config.json` — persistent settings (JSONC)

```jsonc
{
    "llm": {
        "provider": "ollama",
        "host": "http://localhost:11434",
        "timeout": 900,
        "models": {
            "extraction": "gemma4:26b",
            "synthesis": "qwen3.5"
        },
        "fallback_model": "llama3.2",
        "thinking_mode": {
            "extraction": false,
            "synthesis": false
        }
    }
}
```

Flat legacy keys (`llm_provider`, `ollama_model`, …) still work. Nested `llm`
is expanded by `utils/app_config.py`. Precedence: **CLI / env > config.json >
Config defaults**.

CLI / env overrides for experiments without editing the file:

| CLI | Env | Effect |
|---|---|---|
| `--model-extraction` / `--model` on `analyse.py` | `LLM_MODEL_EXTRACTION` | Extraction model |
| `--model-synthesis` / `--model` on `synthesize.py` | `LLM_MODEL_SYNTHESIS` | Synthesis model |
| — | `LLM_FALLBACK_MODEL` | Fallback id |

### Comparative extraction test (Rochecardon)

Requires Ollama with `gemma4:26b` and `qwen3.5` installed:

```bash
# Windows
.\.venv\Scripts\python.exe -m pytest tests/test_model_comparison_rochecardon.py -q

# Linux / WSL
.venv/bin/python -m pytest tests/test_model_comparison_rochecardon.py -q
```

Report written to `work/logs/llm/rochecardon_model_comparison.md` (and `.csv`).
Both models run the same « garnis insalubres » excerpt with thinking disabled;
the report compares schema validity, citation grounding, and absence of an
unqualified « usine toxique » overclaim.

---

## Installation reference (summary)

> Detailed step-by-step guide: see [Step-by-step installation](#step-by-step-installation) at the top of this document.

**Python 3.11+** (tested under 3.12).

```bash
python -m venv .venv

# Windows
.\.venv\Scripts\activate
# Linux/macOS / WSL
source .venv/bin/activate

pip install -r requirements.txt
pip install -e ../shared/ollama_shared   # shared Ollama client
```

### Ollama

```bash
ollama serve          # if the service is not already running
ollama pull gemma4:26b
ollama pull qwen3.5
ollama pull llama3.2  # optional fallback
```

### Optional dependencies

```bash
# OCR — PaddleOCR (pip only, no Tesseract)
pip install paddlepaddle paddleocr

# Automated browser (last resort)
pip install playwright && playwright install chromium
```

---

## Usage — CLI

### `collecte.py` — collection

```bash
# Standard collection
python collecte.py --query "valmontagne" --connector numelyo

# Dry-run (search + resolution, without heavy PDFs)
python collecte.py --query "valmontagne" --connector numelyo --dry-run

# Batch of queries
python collecte.py --queries-file queries.txt --connector numelyo

# PaddleOCR for scanned documents / images
python collecte.py --query "sujet" --connector numelyo --enable-ocr --ocr-lang fra
```

| Argument | Default | Description |
|---|---|---|
| `--query` / `--queries-file` | — | Query(ies) — one of the two is required |
| `--connector` | `numelyo` | Source connector (`numelyo`, `archives_rhone`, `archives_map`, `catalog_html`) |
| `--output-dir` | `work/research` | Markdown folder |
| `--download-dir` | `work/downloads` | PDF / image cache |
| `--dry-run` | off | Without heavy download |
| `--max-results` | 20 | Max number of documents |
| `--match-mode` | `normalized` | `exact` / `normalized` / `fuzzy` |
| `--context-window` | 160 | Context window (characters) |
| `--enable-ocr` | off | **PaddleOCR** fallback if native text is insufficient |
| `--ocr-lang` | `fra` | OCR language (`fra`→`fr` PaddleOCR) |
| `--timeout` / `--delay` | 30 / 1.0 | HTTP (seconds) |
| `--verbose` | off | DEBUG logs |

### `analyse.py` — per-document LLM analysis

```bash
# Analyze sources with at least one mechanical match
python analyse.py --input work/research/2026-06-28_valmontagne_collecte.md --only-matches

# Force re-analysis of all sources
python analyse.py --input work/research/2026-06-28_valmontagne_collecte.md --force

# Explicit extraction model (does not overwrite the collection file)
python analyse.py --input work/research/…_collecte.md --model-extraction gemma4:26b --only-matches

# Write to another file
python analyse.py --input work/research/…_collecte.md --output work/research/…_collecte_analyse_eval.md
```

| Argument | Default | Description |
|---|---|---|
| `--input` | — | Collection Markdown (required) |
| `--output` | `…_collecte_analyse_{model}.md` next to `--input` | Enriched file (use `--in-place` to overwrite the collection) |
| `--in-place` | off | Enrich `--input` directly |
| `--download-dir` | `work/downloads` | Folder of downloaded PDFs / images |
| `--only-matches` | off | Skip sources with no mechanical match |
| `--skip-existing` / `--no-skip-existing` | on | Skip sources already analyzed |
| `--force` | off | Re-analyze even if already done |
| `--llm` | config `llm_provider` | `ollama` \| `openai` \| `openrouter` \| `perplexity` |
| `--model-extraction` | `llm.models.extraction` | Model for grounded claim extraction |
| `--model` | same as `--model-extraction` | Alias for the extraction model |
| `--timeout` | config.json | Generation timeout (s) |
| `--enable-ocr` | off | Re-extraction via **PaddleOCR** if native text is insufficient |
| `--ocr-lang` | `fra` | OCR language (`fra`→`fr` PaddleOCR) |
| `--verbose` | off | DEBUG logs |

### `synthesize.py` — synthesis and context

```bash
# Multi-site synthesis (default): merge all connectors for a keyword
python synthesize.py --query "valmontagne"

# Single collection file
python synthesize.py --input work/research/2026-06-28_valmontagne_numelyo_collecte.md

# Context for writing a text (article, note, post…)
python synthesize.py --query "valmontagne" --mode contexte

# Explicit synthesis model
python synthesize.py --query "valmontagne" --model-synthesis qwen3.5

# Without LLM (deterministic template)
python synthesize.py --query "valmontagne" --llm none
```

| Argument | Default | Description |
|---|---|---|
| `--query` | — | Keyword: discover & merge all site files under `work/research/` |
| `--input` | — | Single collection Markdown (alternative to `--query`) |
| `--research-dir` | `work/research` | Folder scanned when using `--query` |
| `--output-dir` | `work/synthesys` | Output folder |
| `--mode` | `synthese` | `synthese` or `contexte` |
| `--llm` | config `llm_provider` | `ollama` \| `openai` \| `openrouter` \| `perplexity` \| `none` |
| `--model-synthesis` | `llm.models.synthesis` | Model for long-context synthesis |
| `--model` | same as `--model-synthesis` | Alias for the synthesis model |
| `--timeout` | config.json | Generation timeout (s) |

**Logs** = technical output (console). **Markdown** = business output. The two are independent.

---

## LLM gateway and shared Ollama package

All analyse / synthesize completions go through a **single component**, with a **task** role:

```python
from pipeline.llm_gateway import build_llm_gateway
from pipeline.llm_task_models import get_model_for_task

model = get_model_for_task("extraction", config)  # or "synthesis"
gateway = build_llm_gateway(config, task="extraction", operation="analyse")
text = gateway.complete(prompt, system="…")  # uses gateway.think / temperature
```

| Provider (`llm_provider` / `--llm`) | Notes |
|---|---|
| `ollama` (default) | Local via `../shared/ollama_shared`; lists `/api/tags` and falls back if needed |
| `openai` / `openrouter` / `perplexity` | OpenAI-compatible HTTP; set the matching `*_API_KEY` |
| `none` | Template synthesis only (no API call) |

`config.json` is **JSONC** (comments allowed). Call telemetry is written to rotating JSONL under `work/logs/llm/llm_calls.jsonl`. Per-model validation counters: `pipeline.llm_validation_stats`.

`pipeline/llm_client.py` only **re-exports** gateway symbols (plus `get_model_for_task`) for compatibility.

The Ollama transport itself is factorized in `../shared/ollama_shared/` and reused by:

- **ArchivTrace** (this project) — when `llm_provider=ollama`
- **[YouTube2Post](https://github.com/fdepierre/YouTube2Post)** — chat on transcripts

```python
from ollama_shared import OllamaService, DEFAULT_MODEL  # "qwen3.5"

service = OllamaService(model="qwen3.5")
text = service.generate("Prompt…", system="Instructions…", think=False)
```

If the linter reports `ollama_shared` as missing: check that the venv is selected and that `pyrightconfig.json` is present.

---

## Tests

### How to run

Use the project venv (never system Python for full deps):

| Platform | Command |
|---|---|
| Windows (PowerShell) | `.\.venv\Scripts\python.exe -m pytest -q` |
| Linux / WSL | `.venv/bin/python -m pytest -q` |

### Test plan (tiers)

Run **T0 → T1** before every merge. Run **T2** when changing prompts, models, or synthesis validation. Run **T3** before a release or after OCR / connector / LLM routing changes.

| Tier | Goal | Command | Needs |
|---|---|---|---|
| **T0 — Fast unit** | Connectors, Markdown, config, OCR helpers, gateway mocks | `pytest -q --ignore=tests/test_model_comparison_rochecardon.py` | venv only |
| **T1 — Grounding / synthesis contract** | Reject `[0]`, unknown `[S:n]`, claim/source mismatch; prompt v2 | `pytest tests/test_prompt_grounding.py tests/test_synthesis_grounding.py tests/test_synthesis.py tests/test_synthesis_structure.py -q` | venv only |
| **T2 — Live model smoke** | Comparative extraction gemma4 vs qwen3.5 (Rochecardon garnis) | `pytest tests/test_model_comparison_rochecardon.py -q` | Ollama + models installed |
| **T3 — Manual pipeline smoke** | End-to-end without overwriting historical `work/` files | See checklist below | Ollama (+ OCR optional) |

**T3 checklist** (write under `work/.../eval_YYYY-MM-DD/`):

1. Analyse an existing collecte (or OCR variant):  
   `analyse.py --input … --output-dir work/research/eval_…` (+ `--enable-ocr` if needed).
2. Synthesize with grounded path:  
   `synthesize.py --input …_analyse….md --output-dir work/synthesys/eval_…`.
3. Spot-check the Markdown: every fact under **Faits établis et sourcés** has `[S:n]`; no `[0]` / bare `[n]`; invalid LLM → banner « Synthèse non validée », not unsourced prose.
4. Optional: compare `gemma4-26b` vs OCR analyse inputs; keep reports under `work/logs/llm/eval_…/`.

### Coverage map

| Area | Test files |
|---|---|
| Connectors (Numelyo, Rhône, Archiv'MH, catalog HTML) | `test_numelyo_connector.py`, `test_archives_rhone_connector.py`, `test_archives_map_connector.py`, `test_catalog_html_connector.py` |
| Download strategies / collector dry-run | `test_strategies.py`, `test_collector.py` |
| Keywords, paths, merge, strings | `test_keyword_matcher.py`, `test_research_paths.py`, `test_analyse_paths.py`, `test_merge_collections.py`, `test_strings.py` |
| PDF / OCR / analyse policy | `test_text_extractor.py`, `test_ocr.py`, `test_collection_analyzer.py`, `test_analyse_policy.py` |
| Markdown report / patch / round-trip | `test_markdown_reporter.py`, `test_markdown_patcher.py`, `test_markdown_roundtrip.py` |
| LLM gateway, task models, config | `test_llm_gateway.py`, `test_llm_task_models.py`, `test_llm_idea_extractor.py`, `test_llm_resume.py`, `test_llm_max_chars.py`, `test_config_precedence.py`, `test_ollama_shared.py` |
| Grounded extraction + synthesis | `test_prompt_grounding.py`, `test_synthesis_grounding.py`, `test_synthesis.py`, `test_synthesis_structure.py` |
| Historical validation (corroboration, critique externe, NLI, CoVe) | `test_historical_validation.py` |
| Live Ollama comparison | `test_model_comparison_rochecardon.py` |

### Status snapshot (2026-08-11)

| Check | Result |
|---|---|
| Collected tests (sans live Ollama) | 175 |
| T0+T1 | **175 passed** |
| Historical validation | corroboration + critique externe + NLI + CoVe |
| Scripts | `synthesize.py`, `verify.py` |

Re-run and refresh this snapshot after meaningful pipeline changes.

---

## Adding a new source

1. **Create** package `connectors/ma_source/` with `connector.py` (and optional `parsing.py`):

```python
# connectors/ma_source/connector.py
class MaSourceConnector(Connector):
    name = "ma_source"
    root_source = "archives.example.org"

    def build_search_url(self, query: str) -> str: ...
    def search(self, query: str) -> list[DocumentCandidate]: ...
    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument: ...
    def build_strategies(self) -> list[DownloadStrategy]: ...
```

```python
# connectors/ma_source/__init__.py
from connectors.ma_source.connector import MaSourceConnector
__all__ = ["MaSourceConnector"]
```

2. **(Optional)** Add a strategy under `strategies/` if the download differs from existing cases.

3. **Register** in `connectors/__init__.py`:

```python
REGISTRY = {
    NumelyoConnector.name: NumelyoConnector,
    MaSourceConnector.name: MaSourceConnector,
}
```

4. **Test**: offline parsing with an HTML fixture + URL test.

No changes to the pipeline, reporter, or synthesizer are required.

---

## Complete example

Documentary search for “valmontagne” in the Lyon press (Numelyo):

```bash
# 1. Collection (3 documents max)
python collecte.py --query "valmontagne" --connector numelyo --max-results 3

# 2. Per-document LLM analysis (sources with matches)
python analyse.py --input work/research/2026-06-28_valmontagne_collecte.md --only-matches

# 3. Global corpus synthesis
python synthesize.py --input work/research/2026-06-28_valmontagne_collecte.md

# 4. Context dossier for writing your text
python synthesize.py --input work/research/2026-06-28_valmontagne_collecte.md --mode contexte
```

Result in `work/research/` / `work/synthesys/`:

```
2026-06-28_valmontagne_collecte.md    ← sources, excerpts, LLM ideas
2026-06-28_valmontagne_synthese.md    ← research note
2026-06-28_valmontagne_contexte.md    ← ready for writing
```

The `_contexte.md` file can then be passed as-is to an LLM with the instruction: *“Write a text from this documentary dossier.”* — or serve as a base for your own writing.

Outputs are written under `work/research/` and `work/synthesys/` (gitignored).
