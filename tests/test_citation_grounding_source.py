"""Citations are checked against the source text only, never against the LLM output.

Regression for the former ``_source_text_blob``, which appended the LLM analysis
(``llm_ideas``) to the text a citation had to be found in: since the analysis
contains its own ``citation_exacte``, an invented citation was always "found".
"""

from __future__ import annotations

from pathlib import Path

from pipeline.grounded_claims import (
    NOT_IN_EXCERPTS,
    SOURCE_TEXT_UNAVAILABLE,
    collect_grounded_claims,
)
from pipeline.markdown_reader import ParsedCollection, ParsedSource
from pipeline.source_text import SourceTextLoader
from pipeline.synthesis_structure import build_source_catalog

INVENTED = "Le château fut rasé en 1793 par ordre du district"


def _ideas(citation: str) -> str:
    return f"""## Affirmations structurées (JSON)
```json
{{
  "document_status": "ok",
  "affirmations": [
    {{
      "citation_exacte": "{citation}",
      "affirmation": "Une affirmation.",
      "theme": "patrimoine",
      "niveau_confiance": "eleve",
      "statut": "confirme_par_le_document"
    }}
  ],
  "limites": ""
}}
```
"""


def _collect(source: ParsedSource, download_dir: Path):
    collection = ParsedCollection(
        path=Path("x.md"), query="Rochecardon", raw_text="",
        connector="archives_rhone", sources=[source],
    )
    catalog = build_source_catalog(collection)
    loader = SourceTextLoader(connector="archives_rhone", download_dir=download_dir)
    return collect_grounded_claims(collection, catalog, source_text=loader)


def _source(**kwargs) -> ParsedSource:
    base = dict(index=1, title="Garnis insalubres", source_url="https://archives.rhone.fr/ark:/1",
                connector="archives_rhone", source_type="image", match_count=1)
    base.update(kwargs)
    return ParsedSource(**base)


def test_citation_only_in_llm_output_is_not_grounded(tmp_path):
    source = _source(excerpts=["Cette usine occupait le château de Rochecardon"],
                     llm_ideas=_ideas(INVENTED))
    grounded, unverified = _collect(source, tmp_path)
    assert grounded == []
    # Only excerpts could be read: the citation is not refuted, just not re-verifiable
    assert unverified[0].reason == NOT_IN_EXCERPTS
    assert unverified[0].citation_exacte == INVENTED  # kept as written, never altered


def test_citation_absent_from_the_whole_document(tmp_path):
    document = tmp_path / "document.txt"
    document.write_text("Cette usine occupait le château de Rochecardon.", encoding="utf-8")
    source = _source(excerpts=[], llm_ideas=_ideas(INVENTED), local_file=document)
    grounded, unverified = _collect(source, tmp_path)
    assert grounded == []
    assert unverified[0].reason == "citation_non_retrouvee_dans_source"


def test_windows_path_of_a_notebook_is_found_on_linux(tmp_path, monkeypatch):
    (tmp_path / "work" / "downloads").mkdir(parents=True)
    (tmp_path / "work" / "downloads" / "doc.txt").write_text(
        "Cette usine occupait le château de Rochecardon.", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    source = _source(excerpts=[], local_file=Path("work\\downloads\\doc.txt"))
    loader = SourceTextLoader(connector="archives_rhone", download_dir=tmp_path)
    assert loader(source).complete


def test_legacy_notebook_without_source_text_is_not_strengthened(tmp_path):
    # No local file, no excerpt: the claim can not be re-checked
    source = _source(excerpts=[], llm_ideas=_ideas(INVENTED))
    grounded, unverified = _collect(source, tmp_path)
    assert grounded == []
    assert unverified[0].reason == SOURCE_TEXT_UNAVAILABLE


def test_citation_found_in_the_downloaded_document(tmp_path):
    document = tmp_path / "document.txt"
    document.write_text("Rapport de 1902. Cette usine n'occupait pas le château de "
                        "Rochecardon, contrairement à la rumeur.", encoding="utf-8")
    citation = "Cette usine n'occupait pas le château de Rochecardon"
    source = _source(excerpts=[], llm_ideas=_ideas(citation), local_file=document)
    grounded, unverified = _collect(source, tmp_path)
    assert [c.citation_match for c in grounded] == ["exact"]
    assert grounded[0].citation_exacte == citation  # the negation is preserved


def test_the_loader_never_returns_the_llm_analysis(tmp_path):
    source = _source(excerpts=[], llm_ideas=_ideas(INVENTED))
    loader = SourceTextLoader(connector="archives_rhone", download_dir=tmp_path)
    assert loader(source) is None
