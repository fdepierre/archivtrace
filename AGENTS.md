# Agent notes — ArchivTrace

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
nested `llm.models` in `config.json` (`extraction` → gemma4:26b, `synthesis` → qwen3.5,
`fallback_model` → llama3.2). Thinking defaults: both off (synthesis thinking
often drops required JSON fences). Missing Ollama tags → warn + fallback, no crash.

**Docs split:** README = architecture / contracts / config / CLI.
Module docstrings = function-level behaviour. Keep `README.md` / `README-FR.md` in sync.

Rotating JSONL logs: `work/logs/llm/llm_calls.jsonl` (tokens / duration / provider — basis for cost analysis).

Before running or debugging CLI commands, follow:

- `.cursor/skills/cross-platform-runtime/SKILL.md`
- `.cursor/skills/extract-archives-workflow/SKILL.md`

Project rule (always on): `.cursor/rules/cross-platform.mdc`.

## CLI vs config (UX)

Daily workflow uses short intention flags (`--query`, `--input`, `--connector`, `--mode`).
Policies live in `config.json`:

- `analyse.auto_ocr` / `analyse.two_pass_extraction`
- `synthesis.facts_mode` (`tiered` | `strict` | `all`)
- `synthesis.verify_nli` / `synthesis.verify_cove` / `synthesis.nli_llm`

`verify.py` is deprecated; synthesis applies NLI/CoVe from config.
Callable API: `pipeline.run_api.run_analyse` / `run_synthesize` (future web UI).

