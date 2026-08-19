"""Classify whether a document is archival-probative via heuristics and/or LLM."""

from __future__ import annotations

import logging
import re

from pipeline.llm_gateway import LlmGateway
from pipeline.prompt_schemas import (
    ClassifySourceResult,
    PromptValidationError,
    validate_classify_response,
)
from pipeline.prompts import CLASSIFY_SOURCE_PROMPT

logger = logging.getLogger(__name__)

# Connectors that emit archival / institutional digitised holdings.
_ARCHIVAL_CONNECTORS = frozenset(
    {
        "numelyo",
        "archives_rhone",
        "archives_map",
        "gallica",
        "bnf",
    }
)

_NON_PROBATIVE_HOST_RE = re.compile(
    r"(wikipedia\.org|wikimedia\.org|wikidata\.org|"
    r"blogspot\.|wordpress\.com|medium\.com|"
    r"reddit\.com|quora\.com|facebook\.com|twitter\.com|x\.com)",
    re.I,
)

_ARCHIVAL_HOST_RE = re.compile(
    r"(archives\.[a-z0-9.-]+|numelyo\.|gallica\.bnf\.fr|"
    r"ark:/|catalogue\.bnf\.fr|archives-map\.culture\.gouv\.fr)",
    re.I,
)


def classify_source_heuristic(
    *,
    title: str = "",
    url: str | None = None,
    connector: str | None = None,
    source_type: str | None = None,
) -> ClassifySourceResult | None:
    """Deterministic classification when metadata is decisive; else None."""
    url_l = (url or "").casefold()
    title_l = (title or "").casefold()
    conn = (connector or "").strip().casefold()

    if _NON_PROBATIVE_HOST_RE.search(url_l) or "wikipédia" in title_l or "wikipedia" in title_l:
        return ClassifySourceResult(
            classe="non_probante",
            confiance="eleve",
            justification="Encyclopédie / réseau social / blog : non probant pour ce pipeline.",
            utilisable_comme_preuve=False,
        )

    if conn in _ARCHIVAL_CONNECTORS or _ARCHIVAL_HOST_RE.search(url_l or ""):
        # Do NOT assign preuve_primaire by connector alone — critique externe
        # (source_criticism) upgrades clean records after catalog build.
        return ClassifySourceResult(
            classe="non_determine",
            confiance="moyen",
            justification=(
                f"Source institutionnelle / archives (connecteur={conn or 'url'}) ; "
                "classe non_determine en attendant la critique externe."
            ),
            utilisable_comme_preuve=True,
        )

    if source_type and source_type.casefold() in {"webpage", "unknown"}:
        return ClassifySourceResult(
            classe="non_determine",
            confiance="faible",
            justification="Type de source ambigu ; classification LLM recommandée.",
            utilisable_comme_preuve=False,
        )
    return None


class SourceClassifier:
    """Ask the LLM whether a source can be used as archival proof."""

    def __init__(self, *, client: LlmGateway | None = None) -> None:
        self.client = client

    def classify(
        self,
        *,
        query: str,
        title: str,
        url: str | None = None,
        connector: str | None = None,
        source_type: str | None = None,
        cote: str | None = None,
        snippet: str | None = None,
        use_llm: bool = True,
    ) -> ClassifySourceResult | None:
        """Return classification: heuristic first, optional LLM fallback."""
        heuristic = classify_source_heuristic(
            title=title,
            url=url,
            connector=connector,
            source_type=source_type,
        )
        if heuristic is not None and heuristic.classe != "non_determine":
            return heuristic

        if not use_llm or self.client is None or not self.client.is_available():
            return heuristic

        prompt = CLASSIFY_SOURCE_PROMPT.render_user(
            query=query,
            title=title,
            url=url or "—",
            connector=connector or "—",
            source_type=source_type or "—",
            cote=cote or "—",
            snippet=(snippet or "")[:500],
        )
        try:
            raw = self.client.complete(
                prompt,
                system=CLASSIFY_SOURCE_PROMPT.system,
                operation="classify_source",
            )
            return validate_classify_response(raw)
        except PromptValidationError as exc:
            logger.error("classify_source invalid for %r: %s", title, exc)
            return heuristic
        except Exception as exc:  # noqa: BLE001
            logger.warning("classify_source failed for %r: %s", title, exc)
            return heuristic
