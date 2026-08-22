"""Extract thematic ideas from document text via the LLM gateway.

After mechanical keyword matching, this component sends relevant portions of
the extracted text to the configured LLM and asks for structured claims with
mandatory verbatim citations (prompt ``analyze_document``).

Optional second pass (``two_pass_extraction``) uses
``analyze_document_descriptive`` when the strict pass yields no confirmed
claims — those results stay ``statut=insuffisant`` (tier C / hypotheses).
"""

from __future__ import annotations

import logging

from models import ExtractedText, KeywordMatch, LlmExtraction
from config import DEFAULT_LLM_MAX_CHARS
from pipeline.llm_gateway import LlmGateway
from pipeline.prompt_schemas import (
    AnalyzeDocumentResult,
    Affirmation,
    PromptValidationError,
    extract_json_payload,
    render_analyze_markdown,
    validate_analyze_response,
)
from pipeline.prompts import (
    ANALYZE_DOCUMENT_DESCRIPTIVE_PROMPT,
    ANALYZE_DOCUMENT_PROMPT,
)
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
        two_pass_extraction: bool = False,
    ) -> None:
        """Bind the shared LLM gateway and per-document char budget."""
        self.client = client
        self.max_chars = max_chars
        self.two_pass_extraction = two_pass_extraction
        self.prompt = ANALYZE_DOCUMENT_PROMPT
        self.descriptive_prompt = ANALYZE_DOCUMENT_DESCRIPTIVE_PROMPT

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
            self.prompt,
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
            raw = self._retry_json_if_needed(raw, user_prompt, self.prompt.system)
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
                # Still try descriptive pass if enabled — may salvage pistes.
                if self.two_pass_extraction:
                    descriptive = self._run_descriptive_pass(
                        query,
                        title,
                        sample,
                        matches,
                        source=source,
                        cote=cote,
                        date=date,
                    )
                    if descriptive is not None and descriptive.affirmations:
                        body = render_analyze_markdown(descriptive)
                        return LlmExtraction(
                            body=body,
                            model=self.client.model,
                            needs_review=True,
                            error=(
                                "À revoir manuellement — passe stricte invalide ; "
                                "passe descriptive (pistes uniquement)"
                            ),
                            prompt_version=self.descriptive_prompt.version,
                            claims=descriptive.model_dump(),
                            raw_response=raw,
                        )
                return LlmExtraction(
                    body="",
                    model=self.client.model,
                    error=f"À revoir manuellement — sortie LLM invalide: {exc}",
                    needs_review=True,
                    prompt_version=self.prompt.version,
                    raw_response=raw,
                )
            VALIDATION_STATS.record(self.client.model, success=True)

            confirmed = [
                a
                for a in parsed.affirmations
                if a.statut == "confirme_par_le_document"
            ]
            needs_second = self.two_pass_extraction and (
                not confirmed or parsed.document_status == "a_revoir_manuellement"
            )
            if needs_second:
                from pipeline.quality_report import EXTRACTION_QUALITY

                EXTRACTION_QUALITY.record_two_pass()
                descriptive = self._run_descriptive_pass(
                    query,
                    title,
                    sample,
                    matches,
                    source=source,
                    cote=cote,
                    date=date,
                )
                if descriptive is not None and descriptive.affirmations:
                    parsed = self._merge_pass_results(parsed, descriptive)

            from pipeline.quality_report import EXTRACTION_QUALITY

            for claim in parsed.affirmations:
                EXTRACTION_QUALITY.record_claim(
                    confirmed=claim.statut == "confirme_par_le_document"
                )

            body = render_analyze_markdown(parsed)
            needs_review = parsed.document_status == "a_revoir_manuellement" or not any(
                a.statut == "confirme_par_le_document" for a in parsed.affirmations
            )
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

    def _run_descriptive_pass(
        self,
        query: str,
        title: str,
        sample: str,
        matches: list[KeywordMatch],
        *,
        source: str | None,
        cote: str | None,
        date: str | None,
    ) -> AnalyzeDocumentResult | None:
        """Second pass: descriptive mentions only (always statut=insuffisant)."""
        logger.info("Second-pass descriptive extraction for %r", title)
        user_prompt = self._build_prompt(
            self.descriptive_prompt,
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
                system=self.descriptive_prompt.system,
                operation="analyse_descriptive",
            )
            raw = self._retry_json_if_needed(
                raw, user_prompt, self.descriptive_prompt.system
            )
            parsed = validate_analyze_response(raw, document_text=sample)
            # Force tier-C: never promote descriptive-pass claims.
            forced: list[Affirmation] = []
            for claim in parsed.affirmations:
                forced.append(
                    claim.model_copy(update={"statut": "insuffisant"})
                )
            return parsed.model_copy(
                update={
                    "affirmations": forced,
                    "document_status": (
                        "ok"
                        if forced
                        else parsed.document_status
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Descriptive pass failed for %r: %s", title, exc)
            return None

    @staticmethod
    def _merge_pass_results(
        strict: AnalyzeDocumentResult,
        descriptive: AnalyzeDocumentResult,
    ) -> AnalyzeDocumentResult:
        """Keep confirmed claims from pass 1; append unique descriptive pistes."""
        seen_cits = {
            (a.citation_exacte or "").casefold().strip() for a in strict.affirmations
        }
        merged = list(strict.affirmations)
        for claim in descriptive.affirmations:
            key = (claim.citation_exacte or "").casefold().strip()
            if key and key in seen_cits:
                continue
            if key:
                seen_cits.add(key)
            merged.append(claim)
        status = strict.document_status
        if any(a.statut == "confirme_par_le_document" for a in merged):
            status = "ok"
        return strict.model_copy(
            update={
                "affirmations": merged,
                "document_status": status,
                "limites": (
                    (strict.limites or "")
                    + (
                        " | Passe descriptive: "
                        + (descriptive.limites or "mentions littérales ajoutées")
                        if descriptive.affirmations
                        else ""
                    )
                ).strip(" |"),
            }
        )

    def _retry_json_if_needed(self, raw: str, user_prompt: str, system: str) -> str:
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
                system=system,
                operation="analyse_repair",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("JSON repair call failed: %s", exc)
            return raw

    def _build_prompt(
        self,
        prompt,
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
        return prompt.render_user(
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

        return (lead + body)[: self.max_chars] if lead else body[: self.max_chars]
