"""Extract thematic ideas from document text via the LLM gateway.

After mechanical keyword matching, this component sends relevant portions of
the extracted text to the configured LLM and asks for structured claims with
mandatory verbatim citations (prompt ``analyze_document``).
"""

from __future__ import annotations

import logging

from models import ExtractedText, KeywordMatch, LlmExtraction
from config import DEFAULT_LLM_MAX_CHARS
from pipeline.llm_gateway import LlmGateway
from pipeline.prompt_schemas import (
    PromptValidationError,
    extract_json_payload,
    render_analyze_markdown,
    validate_analyze_response,
)
from pipeline.prompts import ANALYZE_DOCUMENT_PROMPT
from pipeline.llm_validation_stats import VALIDATION_STATS
from utils.strings import truncate

logger = logging.getLogger(__name__)


class LlmIdeaExtractor:
    """Ask the configured LLM gateway to extract grounded claims for a keyword."""

    def __init__(
        self,
        *,
        client: LlmGateway,
        max_chars: int = DEFAULT_LLM_MAX_CHARS,
    ) -> None:
        """Bind the shared LLM gateway and per-document char budget."""
        self.client = client
        self.max_chars = max_chars
        self.prompt = ANALYZE_DOCUMENT_PROMPT

    def extract(
        self,
        query: str,
        *,
        title: str,
        text: ExtractedText,
        matches: list[KeywordMatch],
        source: str | None = None,
        cote: str | None = None,
        date: str | None = None,
    ) -> LlmExtraction:
        """Run LLM extraction; never raises into the pipeline."""
        if not self.client.is_available():
            return LlmExtraction(
                body="",
                model=self.client.model,
                error=f"LLM indisponible ({self.client.provider})",
                skipped=True,
            )
        sample = self._build_sample(text, matches)
        if not sample.strip():
            return LlmExtraction(
                body="",
                model=self.client.model,
                error="Aucun texte à analyser",
                skipped=True,
            )
        user_prompt = self._build_prompt(
            query,
            title,
            sample,
            matches,
            source=source,
            cote=cote,
            date=date,
        )
        try:
            raw = self.client.complete(
                user_prompt,
                system=self.prompt.system,
                operation="analyse",
            )
            raw = self._retry_json_if_needed(raw, user_prompt)
            try:
                parsed = validate_analyze_response(raw, document_text=sample)
            except PromptValidationError as exc:
                VALIDATION_STATS.record(self.client.model, success=False)
                logger.error(
                    "Invalid analyze_document output for %r (prompt v%s): %s",
                    title,
                    self.prompt.version,
                    exc,
                )
                snippet = (raw or "")[:240].replace("\n", " ")
                logger.error("Raw LLM snippet: %r", snippet)
                return LlmExtraction(
                    body="",
                    model=self.client.model,
                    error=f"À revoir manuellement — sortie LLM invalide: {exc}",
                    needs_review=True,
                    prompt_version=self.prompt.version,
                    raw_response=raw,
                )
            VALIDATION_STATS.record(self.client.model, success=True)
            body = render_analyze_markdown(parsed)
            needs_review = parsed.document_status == "a_revoir_manuellement"
            return LlmExtraction(
                body=body,
                model=self.client.model,
                needs_review=needs_review,
                error=(
                    "À revoir manuellement — aucune affirmation confirmée"
                    if needs_review
                    else None
                ),
                prompt_version=self.prompt.version,
                claims=parsed.model_dump(),
                raw_response=raw,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM idea extraction failed for %r: %s", title, exc)
            return LlmExtraction(
                body="",
                model=self.client.model,
                error=f"{type(exc).__name__}: {exc}",
                prompt_version=self.prompt.version,
            )

    def _retry_json_if_needed(self, raw: str, user_prompt: str) -> str:
        """One repair pass when the model returned non-JSON / empty content."""
        try:
            extract_json_payload(raw)
            return raw
        except PromptValidationError:
            pass
        repair = (
            user_prompt
            + "\n\n<repair>\nTa réponse précédente n'était pas un JSON valide. "
            "Réponds UNIQUEMENT avec l'objet JSON du schéma, sans markdown ni prose.\n"
            "</repair>"
        )
        logger.warning("Retrying analyze_document for JSON-only repair")
        try:
            return self.client.complete(
                repair,
                system=self.prompt.system,
                operation="analyse_repair",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("JSON repair call failed: %s", exc)
            return raw

    def _build_prompt(
        self,
        query: str,
        title: str,
        sample: str,
        matches: list[KeywordMatch],
        *,
        source: str | None = None,
        cote: str | None = None,
        date: str | None = None,
    ) -> str:
        matches_block = ""
        if matches:
            lines = ["<matches>", "Passages repérés automatiquement (aide) :"]
            for match in matches[:5]:
                page = f" (page {match.page})" if match.page else ""
                lines.append(f"- {truncate(match.excerpt, 300)}{page}")
            lines.append("</matches>")
            matches_block = "\n".join(lines)
        return self.prompt.render_user(
            query=query,
            title=title,
            document_text=sample,
            source=source or "—",
            cote=cote or "—",
            date=date or "—",
            match_count=len(matches),
            matches_block=matches_block,
        )

    def _build_sample(self, text: ExtractedText, matches: list[KeywordMatch]) -> str:
        """Prioritise keyword hits, then cap total length.

        Mechanical excerpts are prepended so the model cites text that is
        guaranteed to be present in the validated sample.
        """
        lead_parts: list[str] = []
        if matches:
            lead_parts.append("[Passages mécaniques prioritaires]")
            for match in matches[:5]:
                page = f" (page {match.page})" if match.page else ""
                lead_parts.append(f"{match.excerpt.strip()}{page}")
            lead_parts.append("")
        lead = "\n".join(lead_parts)

        if not text.pages:
            body = text.full_text
        elif not matches:
            body = text.full_text
        else:
            hit_pages = {m.page for m in matches if m.page is not None}
            chunks: list[str] = []
            for page in text.pages:
                if page.number in hit_pages:
                    chunks.append(f"[Page {page.number}]\n{page.text}")
            for page in text.pages:
                if page.number not in hit_pages and any(
                    abs(page.number - hp) <= 1 for hp in hit_pages
                ):
                    chunks.append(f"[Page {page.number}]\n{page.text}")
            body = "\n\n".join(chunks) if chunks else text.full_text

        budget = max(500, self.max_chars - len(lead))
        return (lead + body)[: self.max_chars] if lead else body[: self.max_chars]
