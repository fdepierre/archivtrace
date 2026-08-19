---
name: cross-platform-runtime
description: >-
  Run and debug extract-archives on Windows PowerShell, WSL, and native Linux.
  Use when installing, activating .venv, running collecte/analyse/synthesize,
  fixing path issues, PDF backend missing, Ollama from WSL, or any
  Windows/WSL/Linux environment mismatch.
---

# Cross-platform runtime (Windows / WSL / Linux)

## Detect the environment first

| Signal | Environment |
|---|---|
| PowerShell / `C:\...` paths | **Windows** |
| Ubuntu terminal, paths `/mnt/c/...` | **WSL** |
| Native Linux home `~/...`, no `/mnt/c` | **Linux** |

Never mix instructions from two columns in the same session.

## Always use the project venv

System `python` often lacks PyMuPDF → text extraction fails on every PDF.

| | Windows | Linux / WSL |
|---|---|---|
| Create | `python -m venv .venv` | `python3 -m venv .venv` |
| Activate | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| Run without activate | `.\.venv\Scripts\python.exe …` | `.venv/bin/python …` |
| Tests | `.\.venv\Scripts\python.exe -m pytest` | `.venv/bin/python -m pytest` |

**Hard rule:** do not run `collecte.py` / `analyse.py` / `synthesize.py` with bare `python` unless `(.venv)` is active or the venv interpreter is used explicitly.

### Separate venvs per OS

A Windows `.venv` is **not** usable from WSL (and vice versa). If the user switches:

1. Create a distinct venv (e.g. `.venv-wsl`) **or** recreate `.venv` on that OS.
2. Reinstall: `pip install -r requirements.txt` (and `pip install -e ../shared/ollama_shared` if needed).

### PowerShell execution policy

If `Activate.ps1` is blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## Paths

- Prefer `pathlib.Path` in Python; never hardcode `C:\` or `/mnt/c/`.
- Relative paths from project root work on all three:
  - `work/research/` — collection / analysis Markdown
  - `work/downloads/` — PDF / image cache
  - `work/synthesys/` — syntheses / writing-context dossiers
  - `work/logs/llm/` — rotating LLM call JSONL (cost telemetry)
- In docs/commands for users: show **three columns** (Windows / Linux / WSL) like the README.
- WSL accessing the Windows tree: `/mnt/c/Users/.../extract-archives` — warn that I/O on `/mnt/c` is slower; a Linux-side clone is optional for heavy runs.

## LLM (gateway)

| Setup | Config |
|---|---|
| Local Ollama | `llm_provider: ollama` + nested `llm.models` (extraction / synthesis) in `config.json` |
| Task model missing | Gateway warns and uses `llm.fallback_model` (`llama3.2`) |
| CLI in **WSL**, Ollama on **Windows** | same host usually works via `localhost` |
| OpenAI / OpenRouter / Perplexity | `llm_provider` + matching `*_API_KEY` env (or `llm_api_key`) |
| Offline template synthesis | `llm_provider: none` / `--llm none` |

Before long `analyse.py` / `synthesize.py` runs: confirm the chosen provider is reachable
(Ollama `/api/tags` and task models installed, or API key present for cloud providers).
Check `llm.models.extraction` / `llm.models.synthesis` (or CLI `--model-extraction` /
`--model-synthesis`).

## PDF / OCR prerequisites

- At least one of: `pymupdf` (fitz), `pdfplumber`, `pypdf` — required for analysis.
- `analyse.py` must fail fast if no PDF backend (do not silently mark all sources failed).
- Optional OCR engine: **PaddleOCR** (`pip install paddlepaddle paddleocr`) then `--enable-ocr`.
  - Implemented in `pipeline/ocr_extractor.py` — not Tesseract.
  - First run downloads models to `~/.paddlex/`; CPU init disables MKLDNN.

## Shell command style

- Windows agent sessions: PowerShell-compatible commands (`Select-Object`, `Get-ChildItem`), or call `.\.venv\Scripts\python.exe` directly.
- WSL/Linux: bash (`ls`, `head`, pipes).
- Avoid `&&` chains that break in older PowerShell; use `;` or separate calls when unsure.

## Quick diagnosis checklist

1. Which OS/shell is this terminal?
2. Is the venv interpreter the one running? (`import fitz` must work)
3. Is the LLM provider up? (Ollama local, or cloud API key for openai/openrouter/perplexity)
4. Do `work/downloads/numelyo/*.pdf` exist for the collection being analysed?
5. Are `config.json` defaults (`llm.models`, `llm_max_chars`, `ollama_timeout`) intentional overrides?

## Additional resources

- Platform command matrix and pitfalls: [reference.md](reference.md)
