# Cross-platform reference

## Command matrix

| Action | Windows (PowerShell) | Linux | WSL |
|---|---|---|---|
| Go to project | `cd C:\Users\...\extract-archives` | `cd ~/.../extract-archives` | `cd /mnt/c/Users/.../extract-archives` |
| Create venv | `python -m venv .venv` | `python3 -m venv .venv` | `python3 -m venv .venv` |
| Activate | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` | `source .venv/bin/activate` |
| Install deps | `pip install -r requirements.txt` | same | same |
| Shared Ollama pkg | `pip install -e ..\shared\ollama_shared` | `pip install -e ../shared/ollama_shared` | same (Linux path) |
| Collection | `python collecte.py --query "…" --connector numelyo` | same | same |
| Analysis | `python analyse.py --input work\research\…_collecte.md --only-matches --model-extraction gemma4:26b` | `work/research/…` | `work/research/…` |
| Synthesis | `python synthesize.py --query "…" --model-synthesis qwen3.5` | same | same |
| Tests | `python -m pytest` | same | same |

Forward slash `research/...` is fine in Python and usually in PowerShell too.

## Known failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| All sources fail text extraction in ~seconds | System Python without PDF backends | Use `.venv` interpreter |
| `ModuleNotFoundError: ollama_shared` | Editable install missing | `pip install -e ../shared/ollama_shared` inside venv |
| `Activate.ps1` cannot be loaded | Execution policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Ollama OK on Windows, fail in WSL | Service not running / wrong host | Start Ollama on Windows; keep `localhost:11434` |
| Cloud LLM: missing API key | `llm_provider` set without env key | Set `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `PERPLEXITY_API_KEY` |
| Weird binary errors importing `fitz` in WSL | Windows venv reused on Linux | Recreate venv under WSL |
| Slow PDF I/O in WSL | Project on `/mnt/c` | Accept slowness or clone into `~/` |

## Config defaults (shared)

Defined in `config.py` and overlaid by `config.json` (JSONC) / `utils/app_config.py`:

- `DEFAULT_LLM_PROVIDER = "ollama"`
- `DEFAULT_LLM_MODEL_EXTRACTION = "gemma4:26b"`
- `DEFAULT_LLM_MODEL_SYNTHESIS = "qwen3.5"`
- `DEFAULT_LLM_FALLBACK_MODEL = "llama3.2"`
- `DEFAULT_LLM_THINKING_EXTRACTION / _SYNTHESIS = False`
- `DEFAULT_LLM_MAX_CHARS = 12_000`
- `DEFAULT_OLLAMA_TIMEOUT = 600.0` (often overridden to `900` in `config.json`)

LLM calls: `pipeline.llm_gateway.build_llm_gateway(..., task=…)`.
Task routing: `pipeline.llm_task_models.get_model_for_task`.
Call logs: `work/logs/llm/llm_calls.jsonl`.

Keep `README.md` and `README-FR.md` Configuration sections in sync when changing defaults.

Override in `config.json` or CLI (`--llm`, `--max-chars`, `--timeout`) — same on every OS.
