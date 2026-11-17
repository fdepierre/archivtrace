# Agent notes — ArchivTrace

Canonical **tool-agnostic** project guide for coding agents and humans
(Cursor, Claude Code, Windsurf, Copilot, …). Editor-specific extras may live
under `.cursor/` or similar; keep the contracts below as the shared source of
truth. Formatting: see `.editorconfig`.

Target platforms: **Windows**, **WSL**, **Linux**.

Working artefacts (not source code) live under **`work/`**:

| Path | Content |
|---|---|
| `work/research/` | Collection + analysis Markdown — `{date}_{query}_{connector}_collecte.md` |
| `work/downloads/` | Downloaded PDFs / images |
| `work/synthesys/` | Multi-site syntheses `{date}_{query}_synthese.md` |

## Configuration

Defaults live only in `config.py`. Overlay: `utils/app_config.resolve_settings()`
(CLI non-None > `config.json` > defaults).

`config.json` is **JSONC** (`//` and `/* */` comments allowed). Keys starting with `_` are ignored.

## Console output

Every command prints through `utils/console.py` (numbered steps, `✓ result (duration)`,
`✖ reason`, `Dir:` / `File:` at the end): a copy of YouTube2Post's `modules/ui.py`, kept in
step by `tests/test_console.py`. No `logging.basicConfig`, no `rich`: call
`console.setup(verbose)` at the start of a command. The log shows warnings and errors only;
info lines are details shown with `-v`. Pipeline code never prints: it receives a
`console.Run` (`progress=`), silent by default.

## Markdown format

Canonical markers / LLM status phrases: `pipeline/markdown_format.py`
(reporter, patcher, reader must not hard-code them).

Business Markdown headings remain in **French** (research output contract). Agent docs and code comments stay in **English**. User-facing French guide: `README-FR.md`.

## OCR

Engine: **PaddleOCR** (`paddlepaddle` + `paddleocr`) via `pipeline/ocr_extractor.py` (`OcrExtractor`).

- Enable: `--enable-ocr` (collecte / analyse); CLI language `--ocr-lang fra` → Paddle code `fr`.
- No Tesseract. First run downloads models (`~/.paddlex/`).
- CPU: code sets `enable_mkldnn=False` (PaddlePaddle 3.3.x workaround).

## LLM

All calls go through **`pipeline.llm_gateway.LlmGateway`** (`build_llm_gateway(..., task=…)`).
`pipeline/llm_client.py` is a **re-export** only (backward compatibility).

Providers: `ollama` (default), `openai`, `openrouter`, `perplexity`, `none`.
Task-scoped models via `pipeline.llm_task_models.get_model_for_task` /
nested `llm.models` in `config.json` (`extraction` → qwen3.5, `synthesis` → qwen3.5,
`fallback_model` → qwen3.5:4b). Thinking defaults: both off (synthesis thinking
often drops required JSON fences). Missing Ollama tags → warn + fallback, no crash.

**Docs split:** README = architecture / contracts / config / CLI.
Module docstrings = function-level behaviour. Keep `README.md` / `README-FR.md` in sync.

Rotating JSONL logs: `work/logs/llm/llm_calls.jsonl` (tokens / duration / provider — basis for cost analysis).

Before running or debugging CLI commands, prefer this file (`AGENTS.md`) and
`README.md` / `README-FR.md`. Optional local Cursor skills under `.cursor/`
(gitignored) may mirror the same guidance but are not part of the shared repo.

## Video transcripts (YouTube2Post)

`import_sources.py` / `pipeline/transcript_import.py` declare YouTube2Post transcripts
(`yt2post-source/1` JSON, source of truth for the text and timestamps) as notebook sources;
`pipeline/transcript_source.py` reads them as timestamped passages and locates citations in
the segments (computed, never asked to the LLM). A transcript is analysed whole, block by
block (`LlmIdeaExtractor.extract_in_blocks`, cache in `work/cache/analyse/`). YouTube2Post playlist records
(`yt2post-playlist/1`) list each video's state; `pipeline/playlist_status.py` derives
where each video stands (`import_sources.py --status`, read only), and
`transcript_import.sync_analysis_file` brings new or re-transcribed videos into an existing
`_analyse_<model>.md` before `analyse.py` runs. Citation grounding uses the source text only
(`pipeline/source_text.py`), never the LLM analysis. Videos are `preuve_secondaire`. Data
lineage: `docs/DATA_LINEAGE.md`.

## CLI vs config (UX)

Researcher entry point: `archivtrace.py` (home screen, `config.json` key `sites`,
collect+analyse overlap, resume of the latest notebook). Precise tools stay
`collecte.py`, `analyse.py`, `synthesize.py`. Default single connector is
Wikipedia (`config.DEFAULT_CONNECTOR`); `tous` / `--connectors all` is an
explicit choice of production connectors.

Daily workflow uses short intention flags (`--query`, `--input`, `--connector`, `--mode`).
Policies live in `config.json`:

- `analyse.auto_ocr` / `analyse.two_pass_extraction`
- `synthesis.facts_mode` (`tiered` | `strict` | `all`)
- `synthesis.verify_nli` / `synthesis.verify_cove` / `synthesis.nli_llm`
- `synthesis.classify_sources` (LLM fallback for ambiguous source classes)

`synthesize.py --reverify` re-applies NLI/CoVe on an existing synthesis
without regenerating narrative prose.
Callable API: `pipeline.run_api.run_collect` / `run_analyse` / `run_synthesize` /
`run_reverify` (each returns `RunResult`: `exit_code`, `paths`, optional
`quality_report_path`, `errors`, `stats`). Synthesis render helpers live in
`pipeline.synthesis_render` (used by reverify). Connector metadata:
`connectors.meta.ConnectorInfo` / `list_connector_info()`.
HTTP layer deferred until a front is needed.
OCR optional: `pip install -r requirements-ocr.txt`.
Ollama client: the official `ollama` package, called from `pipeline/llm_gateway.OllamaBackend`.
Wikipedia: default connector when none is named (`--connector wikipedia` still
explicit). MediaWiki API; `wikipedia_lang` default `fr`.

