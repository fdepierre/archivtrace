---
name: extract-archives-workflow
description: >-
  Collect, analyse, and synthesize documentary research Markdown with
  extract-archives (Numelyo, LLM gateway). Use when running or modifying
  collecte.py, analyse.py, synthesize.py, connectors, OCR, keyword matching,
  or research/ Markdown outputs.
---

# extract-archives workflow

## Pipeline order

1. **`collecte.py`** — search → download → text extract → keyword matches → `work/research/{date}_{query}_{connector}_collecte.md`
2. **`analyse.py`** — per-document LLM ideas → `work/research/…_collecte_analyse_{model}.md` (default) or `--in-place`
3. **`synthesize.py`** — corpus synthesis / `--mode contexte` → `work/synthesys/*_synthese.md` / `*_contexte.md`

Do not reintroduce LLM calls into the collection path.

## Before any long analyse run

1. Confirm cross-platform runtime skill: **venv Python** with `import fitz`.
2. LLM reachable: Ollama up **or** cloud provider API key set (`llm_provider` / `--llm`).
3. Prefer `--only-matches` on large corpora.
4. Use `--force` only to reseed the analysis file from a clean collection.

## Resume semantics

- Skip sources already successfully analysed (`llm_analyzed`).
- Retry `failed` / empty LLM blocks.
- Incremental save after each source.

## Connectors

- Production-proven: **`numelyo`**
- Départemental archives: **`archives_rhone`** ([archives.rhone.fr](https://archives.rhone.fr))
- Heritage media library / Archiv'MH: **`archives_map`** ([archives-map.culture.gouv.fr](https://archives-map.culture.gouv.fr))
- Generic: **`catalog_html`** (needs catalog URLs in config/CLI)
- New sources: add `connectors/<name>/` (`connector.py` + optional `parsing.py`); register in `connectors/__init__.py`; keep Markdown as sole business output.

## Research file naming

```text
work/research/{date}_{query}_{connector}_collecte.md
work/research/{date}_{query}_{connector}_collecte_analyse_{model}.md
work/synthesys/{date}_{query}_synthese.md   # multi-site by default
```

Synthesis: `synthesize.py --query <keyword>` merges the best file per connector (prefer `*_analyse_*`) and keeps source URLs.

## OCR

- Native PDF text first (`TextExtractor` → pymupdf / pdfplumber / pypdf).
- Optional engine: **PaddleOCR** in `pipeline/ocr_extractor.py` (`OcrExtractor`).
  - Install: `pip install paddlepaddle paddleocr` (no Tesseract).
  - Flags: `--enable-ocr`, `--ocr-lang fra` (mapped to Paddle `fr`).
  - PDF pages rasterised with PyMuPDF then OCR’d; images OCR’d directly.
  - Init uses `enable_mkldnn=False` (Windows/CPU Paddle 3.3.x workaround).
- Heavy VLM OCR is out of scope unless explicitly requested — same `ExtractedText` contract.

## Config

Read via `utils.app_config.resolve_settings()` / `load_config()`.
Shared defaults live only in `config.py` (`DEFAULT_*`, `Config`).

Precedence: **CLI (non-None) > config.json (JSONC) > Config defaults**.

### LLM gateway (single entry point)

All analyse/synthesize LLM calls go through `pipeline.llm_gateway.build_llm_gateway` /
`LlmGateway` (not raw Ollama/OpenAI clients). `pipeline/llm_client.py` only re-exports.
Task models: `pipeline.llm_task_models.get_model_for_task` (`extraction` / `synthesis`).

| Provider | `--llm` / `llm_provider` | Auth |
|---|---|---|
| Local Ollama | `ollama` (default) | none |
| OpenAI | `openai` | `OPENAI_API_KEY` or `llm_api_key` |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` |
| Perplexity | `perplexity` | `PERPLEXITY_API_KEY` |
| Offline template | `none` | — |

Defaults (nested `llm` in `config.json`): extraction=`gemma4:26b` (thinking off),
synthesis=`qwen3.5` (thinking off — enable only for experiments), fallback=`llama3.2`.
CLI: `--model-extraction` / `--model-synthesis` (or `--model` as alias for the current command).

Rotating JSONL call log (cost analysis): `work/logs/llm/llm_calls.jsonl`.

Keep CLI fallbacks as `default=None` so json/defaults can apply.

## Tests

```text
# Windows
.\.venv\Scripts\python.exe -m pytest

# Linux / WSL
.venv/bin/python -m pytest
```

## Related skill

For OS/shell/venv/LLM path issues, use **cross-platform-runtime**.
