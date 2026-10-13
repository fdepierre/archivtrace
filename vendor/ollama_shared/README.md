# ollama-shared

Client Ollama factorisé pour les projets locaux de **fdepierre** :

- [extract-archives](../extract-archives) — synthèse de collectes documentaires
- [YouTube2Post](https://github.com/fdepierre/YouTube2Post) — chat sur transcripts YouTube

## Installation (editable)

Depuis un projet consommateur :

```bash
pip install -e ../shared/ollama_shared
```

## Usage

```python
from ollama_shared import OllamaService, DEFAULT_MODEL

service = OllamaService(model="qwen3.5")
text = service.generate("Résume ce document.", system="Tu es un archiviste.")
```

Modèle par défaut : **`qwen3.5`** (`ollama pull qwen3.5`).
