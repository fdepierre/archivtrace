"""Extract thematic ideas from document text via the LLM gateway.

After mechanical keyword matching, this component sends relevant portions of
the extracted text to the configured LLM and asks for structured claims with
mandatory verbatim citations (prompt ``analyze_document``).

Optional second pass (``two_pass_extraction``) uses
``analyze_document_descriptive`` when the strict pass yields no confirmed
claims — those results stay ``statut=insuffisant`` (tier C / hypotheses).

A transcript is analysed whole, in consecutive blocks of passages that fit the
character budget (``extract_in_blocks``): one LLM call per block, each block's
citations validated against that block's text, the claims then merged. Each
block's result can be cached, so an interrupted analysis resumes where it
stopped.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path

from config import (
    DEFAULT_LLM_MAX_CHARS,
    DEFAULT_TRANSCRIPT_BLOCK_CHARS,
    DEFAULT_TRANSCRIPT_MAX_CLAIMS,
)
from models import ExtractedPage, ExtractedText, KeywordMatch, LlmExtraction
from pipeline.llm_gateway import LlmGateway
from pipeline.llm_validation_stats import VALIDATION_STATS
from pipeline.prompt_schemas import (
    Affirmation,
    AnalyzeDocumentResult,
    PromptValidationError,
    extract_json_payload,
    render_analyze_markdown,
    transcript_answer_chars,
    transcript_answer_schema,
    validate_analyze_response,
)
from pipeline.prompts import (
    ANALYZE_DOCUMENT_DESCRIPTIVE_PROMPT,
    ANALYZE_DOCUMENT_PROMPT,
    ANALYZE_TRANSCRIPT_PROMPT,
)
from utils.strings import truncate

logger = logging.getLogger(__name__)


def _unit_label(page) -> str:
    """'[Page 3]' for a document, '[Passage 02:05–03:10]' for a transcript."""
    from pipeline.transcript_source import passage_label

    label = passage_label(page)
    return f"[Passage {label[1:-1]}]" if label else f"[Page {page.number}]"


def text_blocks(pages: list[ExtractedPage], max_chars: int) -> list[list[ExtractedPage]]:
    """
    Consecutive passages grouped into blocks whose labelled text fits
    ``max_chars``. Each block after the first starts with the last passage of
    the previous one, so a statement spanning the boundary is read whole once.
    """
    def size(page: ExtractedPage) -> int:
        return len(_unit_label(page)) + len(page.text) + 3

    blocks: list[list[ExtractedPage]] = []
    block: list[ExtractedPage] = []
    used = 0
    for page in pages:
        if block and used + size(page) > max_chars:
            blocks.append(block)
            overlap = block[-1]
            block, used = ([overlap], size(overlap)) if size(overlap) + size(page) <= max_chars else ([], 0)
        block.append(page)
        used += size(page)
    if block:
        blocks.append(block)
    return blocks


def _block_label(block: list[ExtractedPage]) -> str:
    """'[00:00–14:52]' for transcript passages, 'pages 3–7' otherwise."""
    from pipeline.transcript_source import time_range

    first, last = block[0], block[-1]
    if first.start_seconds is not None and last.end_seconds is not None:
        return time_range(first.start_seconds, last.end_seconds)
    return f"pages {first.number}–{last.number}"


class LlmIdeaExtractor:
    """Ask the configured LLM gateway to extract grounded claims for a keyword."""

    def __init__(
        self,
        *,
        client: LlmGateway,
        max_chars: int = DEFAULT_LLM_MAX_CHARS,
        two_pass_extraction: bool = False,
        max_claims: int = DEFAULT_TRANSCRIPT_MAX_CLAIMS,
        block_chars: int = DEFAULT_TRANSCRIPT_BLOCK_CHARS,
    ) -> None:
        """Bind the shared LLM gateway and per-document char budget.

        ``max_claims``: the most claims asked for one block of a transcript.
        ``block_chars``: the size of a transcript's blocks, within ``max_chars``.
        """
        self.client = client
        self.block_chars = min(block_chars, max_chars)
        self.max_claims = max_claims
        self.transcript_prompt = ANALYZE_TRANSCRIPT_PROMPT
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
        whole_text: bool = False,
        prompt=None,
    ) -> LlmExtraction:
        """Run LLM extraction; never raises into the pipeline.

        ``whole_text``: send all the pages given (one block of a transcript),
        not only the pages around keyword hits. ``prompt``: another prompt
        with the same answer schema (the transcript one); no descriptive pass
        is made with it.
        """
        prompt = prompt or self.prompt
        two_pass = self.two_pass_extraction and prompt is self.prompt
        if not self.client.is_available():
            return LlmExtraction(
                body="",
                model=self.client.model,
                error=f"LLM indisponible ({self.client.provider})",
                skipped=True,
            )
        sample = self._build_sample(text, matches, whole_text=whole_text)
        if not sample.strip():
            return LlmExtraction(
                body="",
                model=self.client.model,
                error="Aucun texte à analyser",
                skipped=True,
            )
        user_prompt = self._build_prompt(
            prompt,
            query,
            title,
            sample,
            matches,
            source=source,
            cote=cote,
            date=date,
        )
        try:
            constrained = self._constraints(prompt)
            raw = self.client.complete(
                user_prompt,
                system=prompt.system,
                operation="analyse",
                **constrained,
            )
            first = raw
            raw = self._retry_json_if_needed(raw, user_prompt, prompt.system, constrained)
            try:
                parsed = validate_analyze_response(raw, document_text=sample)
            except PromptValidationError as exc:
                VALIDATION_STATS.record(self.client.model, success=False)
                logger.error(
                    "Invalid %s output for %r (prompt v%s): %s",
                    prompt.id,
                    title,
                    prompt.version,
                    exc,
                )
                snippet = (raw or "")[:240].replace("\n", " ")
                logger.error("Raw LLM snippet: %r", snippet)
                # Still try descriptive pass if enabled — may salvage pistes.
                if two_pass:
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
                    prompt_version=prompt.version,
                    raw_response=raw,
                )
            VALIDATION_STATS.record(self.client.model, success=True)

            confirmed = [
                a
                for a in parsed.affirmations
                if a.statut == "confirme_par_le_document"
            ]
            if raw is not first:  # the first answer was not JSON: the second one may be shorter
                parsed = parsed.model_copy(update={"limites": (
                    (parsed.limites or "") + " | Réponse obtenue au second essai (la "
                    "première n'était pas un JSON valide) : elle peut être incomplète."
                ).strip(" |")})
            needs_second = two_pass and (
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
                prompt_version=prompt.version,
                claims=parsed.model_dump(),
                raw_response=raw,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM idea extraction failed for %r: %s", title, exc)
            return LlmExtraction(
                body="",
                model=self.client.model,
                error=f"{type(exc).__name__}: {exc}",
                prompt_version=prompt.version,
            )

    def extract_in_blocks(
        self,
        query: str,
        *,
        title: str,
        text: ExtractedText,
        matches: list[KeywordMatch],
        source: str | None = None,
        cote: str | None = None,
        date: str | None = None,
        cache_dir: Path | None = None,
        refresh: bool = False,
        on_block: Callable[[int, int, str], None] | None = None,
    ) -> LlmExtraction:
        """
        Analyse the whole text, block by block (one LLM call each), and merge
        the claims. A block already analysed with the same model, prompt and
        text is read from ``cache_dir`` instead of asking the model again,
        unless ``refresh`` (the new answer then replaces the cached one).
        ``on_block(number, total, label)`` is called before each block.

        Each block is asked with the transcript prompt: the main claims of the
        passage, at most ``max_claims``, whatever the subject. An answer cut by
        the output limit is not repaired: the block is analysed again in two
        halves, and that decision is cached too, so that a later run does not
        ask the cut answer again.
        """
        blocks = text_blocks(text.pages, self.block_chars)
        results: list[tuple[str, LlmExtraction]] = []
        pending = list(blocks)
        number = 0
        while pending:
            block = pending.pop(0)
            number += 1
            label = _block_label(block)
            if on_block is not None:
                on_block(number, number + len(pending), label)
            if len(blocks) > 1 or number > 1:
                logger.info("%s — bloc %d/%d %s", title, number, number + len(pending), label)
            pages = {p.number for p in block}
            block_text = ExtractedText(pages=block, extractor=text.extractor,
                                       quality_note=text.quality_note)
            block_matches = [m for m in matches if m.page in pages]
            key = self._cache_key(query, title, block_text)
            if not refresh and len(block) > 1 and _cached_split(cache_dir, key):
                logger.info("%s — bloc %s : coupé en deux (décision en cache)", title, label)
                half = len(block) // 2
                first = block[:half + 1] if len(block) > 2 else block[:half]
                pending[:0] = [first, block[half:]]
                continue
            extraction = None if refresh else _cache_read(cache_dir, key)
            if extraction is None:
                extraction = self.extract(query, title=title, text=block_text,
                                          matches=block_matches, source=source,
                                          cote=cote, date=date, whole_text=True,
                                          prompt=self.transcript_prompt)
                if extraction.claims is not None:
                    _cache_write(cache_dir, key, extraction)
            if extraction.claims is None and extraction.needs_review and len(block) > 1:
                _cache_split(cache_dir, key)
                # Usually an answer cut by the output limit: too many claims
                # for one call. Analyse the two halves instead (sharing their
                # boundary passage when there are more than two).
                half = len(block) // 2
                logger.warning("%s — bloc %s : réponse invalide, analysé en deux moitiés",
                               title, label)
                first = block[:half + 1] if len(block) > 2 else block[:half]
                pending[:0] = [first, block[half:]]
                continue
            results.append((label, extraction))
        if len(results) == 1:
            return results[0][1]
        return self._merge_blocks(results)

    def _cache_key(self, query: str, title: str, block: ExtractedText) -> str:
        """Same model, prompt, subject and text: the same analysis."""
        payload = json.dumps({
            "model": self.client.model,
            "prompt": f"{self.transcript_prompt.id}.v{self.transcript_prompt.version}",
            "max_claims": self.max_claims,
            "descriptive": self.two_pass_extraction, "query": query, "title": title,
            "text": self._build_sample(block, [], whole_text=True),
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _merge_blocks(self, results: list[tuple[str, LlmExtraction]]) -> LlmExtraction:
        """One analysis from the blocks' analyses; failed blocks are reported."""
        analysed = [(label, r) for label, r in results if r.claims is not None]
        failed = [(label, r) for label, r in results if r.claims is None]
        if not analysed:
            first = failed[0][1]
            first.error = f"{len(failed)} bloc(s) non analysé(s) — {first.error}"
            return first
        merged: list[Affirmation] = []
        seen: set[str] = set()
        limites = [f"Analysé en {len(results)} blocs."]
        for label, result in analysed:
            parsed = AnalyzeDocumentResult.model_validate(result.claims)
            for claim in parsed.affirmations:
                key = (claim.citation_exacte or "").casefold().strip()
                if key and key in seen:
                    continue  # the same citation read twice in the overlap
                seen.add(key)
                merged.append(claim)
            if parsed.limites and parsed.limites.strip() not in {"", "—", "-"}:
                limites.append(f"{label} : {parsed.limites.strip()}")
        for label, result in failed:
            limites.append(f"{label} : NON ANALYSÉ ({result.error or 'échec'})")
        confirmed = any(a.statut == "confirme_par_le_document" for a in merged)
        combined = AnalyzeDocumentResult(
            document_status="ok" if confirmed and not failed else "a_revoir_manuellement",
            affirmations=merged,
            limites=" | ".join(limites),
        )
        needs_review = combined.document_status == "a_revoir_manuellement"
        if failed:
            error = f"À revoir manuellement — {len(failed)} bloc(s) non analysé(s)"
        elif not confirmed:
            error = "À revoir manuellement — aucune affirmation confirmée"
        else:
            error = None
        return LlmExtraction(
            body=render_analyze_markdown(combined),
            model=self.client.model,
            needs_review=needs_review,
            error=error,
            prompt_version=self.transcript_prompt.version,
            claims=combined.model_dump(),
            raw_response="\n\n".join(r.raw_response or "" for _, r in results),
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

    def _constraints(self, prompt) -> dict:
        """
        For the transcript prompt: the answer schema (at most max_claims claims
        of bounded length), and an output limit large enough for the longest
        answer it allows, so that it is never cut.
        """
        if prompt is not self.transcript_prompt:
            return {}
        from pipeline.llm_gateway import CHARS_PER_TOKEN

        longest = -(-transcript_answer_chars(self.max_claims) // CHARS_PER_TOKEN)  # rounded up
        return {"json_schema": transcript_answer_schema(self.max_claims),
                "max_tokens": max(self.client.max_tokens or 0, longest)}

    def _retry_json_if_needed(self, raw: str, user_prompt: str, system: str,
                              constrained: dict | None = None) -> str:
        """One repair pass when the model returned non-JSON / empty content."""
        try:
            extract_json_payload(raw)
            return raw
        except PromptValidationError:
            pass
        limit = (constrained or {}).get("max_tokens", self.client.max_tokens)
        if _looks_cut(raw, limit):
            # The answer reached the output limit: asking again gives the same
            # length, cut again. Leave it invalid: the caller splits the text.
            logger.warning("Answer cut by the output limit (%d characters): not repaired",
                           len(raw))
            return raw
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
                **(constrained or {}),
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
            max_claims=self.max_claims,
        )

    def _build_sample(
        self, text: ExtractedText, matches: list[KeywordMatch], *, whole_text: bool = False
    ) -> str:
        """Prioritise keyword hits, then cap total length.

        Mechanical excerpts are prepended so the model cites text that is
        guaranteed to be present in the validated sample. With ``whole_text``,
        every page is sent with its label (the excerpts are already in it).
        """
        if whole_text:
            body = "\n\n".join(f"{_unit_label(page)}\n{page.text}" for page in text.pages)
            return body[: self.max_chars]
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
                    chunks.append(f"{_unit_label(page)}\n{page.text}")
            for page in text.pages:
                if page.number not in hit_pages and any(
                    abs(page.number - hp) <= 1 for hp in hit_pages
                ):
                    chunks.append(f"{_unit_label(page)}\n{page.text}")
            body = "\n\n".join(chunks) if chunks else text.full_text

        return (lead + body)[: self.max_chars] if lead else body[: self.max_chars]


# An answer longer than this many characters per output token reached the
# limit (French JSON is about 3.5 characters per token)
_CUT_CHARS_PER_TOKEN = 3


def _looks_cut(raw: str, max_tokens: int | None) -> bool:
    """True for an invalid answer as long as the output limit allows: it was cut."""
    return bool(max_tokens) and len(raw or "") >= max_tokens * _CUT_CHARS_PER_TOKEN


def _cached_split(cache_dir: Path | None, key: str) -> bool:
    """True when an earlier run had to split this block: its answer was cut."""
    return cache_dir is not None and (cache_dir / f"{key}.split").exists()


def _cache_split(cache_dir: Path | None, key: str) -> None:
    """Remember that this block is analysed in two halves."""
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.split").write_text("", encoding="utf-8")


def _cache_read(cache_dir: Path | None, key: str) -> LlmExtraction | None:
    """A block analysis saved by a previous run, if any."""
    if cache_dir is None:
        return None
    path = cache_dir / f"{key}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LlmExtraction(**data)
    except (OSError, ValueError, TypeError):
        return None


def _cache_write(cache_dir: Path | None, key: str, extraction: LlmExtraction) -> None:
    """Save a block analysis, so an interrupted run does not ask it again."""
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "body": extraction.body, "model": extraction.model, "error": extraction.error,
        "skipped": extraction.skipped, "needs_review": extraction.needs_review,
        "prompt_version": extraction.prompt_version, "claims": extraction.claims,
        "raw_response": extraction.raw_response,
    }
    tmp = cache_dir / f"{key}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache_dir / f"{key}.json")
