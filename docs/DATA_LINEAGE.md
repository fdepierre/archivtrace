# Data lineage

How information travels through ArchivTrace, and which layer is authoritative for what.
The format of a piece of information follows **who produces it**, not who reads it: one
layer is authoritative, every other form is derived from it, in one direction.

## Layers

| Information | Produced by | Authoritative layer | Derived forms |
|---|---|---|---|
| Downloaded documents (PDF, images, pages) | the source (archives, libraries) | the file in `work/downloads/` | extracted text, keyword excerpts in the notebook |
| Video transcripts (segments, timestamps, metadata) | YouTube2Post (machine) | its `yt2post-source/1` JSON | passages read by `analyse.py`, excerpts in the notebook |
| State of each video of a playlist (transcribed, failed, pending) | YouTube2Post | its `yt2post-playlist/1` record | `import_sources.py --status` (computed each time, never stored) |
| Claims extracted from a source | the LLM, then checked by code | the validated JSON block in the notebook's `### Idées extraites (LLM)` | syntheses |
| Where a citation is in a transcript | code (`pipeline/transcript_source.py`) | the `#### Localisation des citations` lines under the analysis | — |
| Syntheses and writing contexts | the LLM, then a person | the Markdown in `work/synthesys/` | — |

```
source (archive, library, YouTube via YouTube2Post)
        │  download / import (one-way)
        ▼
work/downloads/…  or  YouTube2Post JSON      ← source of truth for the text
        │  collecte.py / import_sources.py: the notebook points to the file
        ▼
work/research/…_collecte.md                  ← research notebook (Markdown)
        │  analyse.py: claims (validated JSON) + computed citation locations
        ▼
work/research/…_collecte_analyse_<model>.md
        │  synthesize.py: only citations found in the source text
        ▼
work/synthesys/…_synthese.md
```

## Rules

- **The source text is never copied as the reference.** The notebook points to the file
  (`Local file:`); the analysis re-reads it.
- **A model's output never proves itself.** A citation is checked against the source text
  only (the file, else the mechanical excerpts): never against the LLM analysis
  (`pipeline/source_text.py`, `pipeline/grounded_claims.py`). A claim whose source text is
  missing stays to be verified (`texte_source_indisponible`).
- **No silent strengthening.** A fuzzy match stays marked fuzzy; the stored citation is never
  rewritten; a video is secondary evidence: it proves a statement is made, not that it is
  true.
- **Versions.** A transcript is identified by its source id (`youtube:<id>`) and its text
  version (a fingerprint). A new version makes the analyses of the previous one obsolete; they
  are kept, marked as such, never silently reused.
- **One way.** The notebook follows the transcripts (`import_sources.py`), and an existing
  analysis file follows the notebook (new or re-transcribed videos are brought in before
  `analyse.py` runs); nothing flows back. The status of a video is derived from these files,
  never kept in a file of its own.
