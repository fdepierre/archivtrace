"""Pydantic schemas and validators for versioned LLM prompt outputs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_TAG_RE = re.compile(r"</?think>", re.IGNORECASE)

ClaimStatut = Literal["confirme_par_le_document", "insuffisant"]
Confidence = Literal["eleve", "moyen", "faible"]
DocumentStatus = Literal["ok", "a_revoir_manuellement"]
SourceClasse = Literal[
    "preuve_primaire", "preuve_secondaire", "non_probante", "non_determine"
]
TemoignageKind = Literal["volontaire", "involontaire", "indetermine"]
SinceriteKind = Literal["sincere", "a_verifier", "indetermine"]


class PoidsPreuve(BaseModel):
    """Internal criticism priors (Gottschalk-inspired), filled at extraction."""

    temoignage: TemoignageKind = "indetermine"
    sincerite: SinceriteKind = "indetermine"


class Affirmation(BaseModel):
    """One grounded claim extracted from a single document."""

    citation_exacte: str = Field(min_length=1)
    affirmation: str = Field(min_length=1)
    theme: str = Field(min_length=1)
    niveau_confiance: Confidence
    statut: ClaimStatut
    poids_preuve: PoidsPreuve = Field(default_factory=PoidsPreuve)

    @field_validator("citation_exacte", "affirmation", "theme", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("poids_preuve", mode="before")
    @classmethod
    def _coerce_poids(cls, value: Any) -> Any:
        if value is None:
            return PoidsPreuve()
        if isinstance(value, str):
            # Allow flat "involontaire" / "volontaire" shorthand.
            low = value.strip().casefold()
            if low in {"volontaire", "involontaire", "indetermine"}:
                return {"temoignage": low, "sincerite": "indetermine"}
            return PoidsPreuve()
        return value


class AnalyzeDocumentResult(BaseModel):
    """Structured output of ``analyze_document`` prompt."""

    document_status: DocumentStatus
    affirmations: list[Affirmation] = Field(default_factory=list)
    limites: str = ""


class ChronologyItem(BaseModel):
    date: str = ""
    periode: str | None = None
    description: str = Field(min_length=1)
    sources: list[int] = Field(default_factory=list)


class VerificationItem(BaseModel):
    categorie: str = Field(min_length=1)
    description: str = Field(min_length=1)
    indices_sources: list[int] = Field(default_factory=list)
    priorite: Literal["haute", "moyenne", "basse"] = "moyenne"
    requetes_web_suggerees: list[str] = Field(default_factory=list)

    @field_validator("requetes_web_suggerees")
    @classmethod
    def _short_queries(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            text = str(item).strip().strip('"').strip("'")
            if not text:
                continue
            # Soft check: prefer 2–6 tokens; keep but do not invent replacements.
            cleaned.append(text)
        return cleaned


class SynthesizeClaimsResult(BaseModel):
    """Structured JSON blocks expected after synthesis narrative (legacy v1)."""

    chronologie: list[ChronologyItem] = Field(default_factory=list)
    points_a_verifier: list[VerificationItem] = Field(default_factory=list)
    sources_par_theme: dict[str, list[int]] = Field(default_factory=dict)


class SynthesisFact(BaseModel):
    """One established fact in synthesize_claims v2 output."""

    texte: str = Field(min_length=1)
    sources: list[int] = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)


class SynthesisTimelineEvent(BaseModel):
    """One chronology event in synthesize_claims v2 output."""

    date: str = ""
    texte: str = Field(min_length=1)
    sources: list[int] = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)


class SynthesisVerificationPoint(BaseModel):
    """Open question / hypothesis — never an established fact."""

    description: str = Field(min_length=1)
    sources_indices: list[int] = Field(default_factory=list)
    statut: str = "à confirmer"
    requetes_web_suggerees: list[str] = Field(default_factory=list)


class SynthesisOutput(BaseModel):
    """Strict JSON-only synthesis payload (prompt synthesize_claims v2+)."""

    faits_etablis: list[SynthesisFact] = Field(default_factory=list)
    # Single-source, citation-backed facts (tier B — research notebook).
    faits_documentes: list[SynthesisFact] = Field(default_factory=list)
    chronologie: list[SynthesisTimelineEvent] = Field(default_factory=list)
    points_a_verifier: list[SynthesisVerificationPoint] = Field(default_factory=list)
    plan_article: list[str] = Field(default_factory=list)


# Bare footnotes / zero ids that must never appear as historical anchors.
_FORBIDDEN_REF_RE = re.compile(
    r"\[(?:0+|S:\s*0+|S:\s*\?|source:[^\]]*)\]",
    re.IGNORECASE,
)
_BARE_BRACKET_NUM_RE = re.compile(r"\[(\d+)\]")
_S_REF_IN_TEXT_RE = re.compile(r"\[S:([\d,\s]+)\]", re.IGNORECASE)


class ClassifySourceResult(BaseModel):
    """Output of ``classify_source`` prompt."""

    classe: SourceClasse
    confiance: Confidence
    justification: str = Field(min_length=1)
    utilisable_comme_preuve: bool


class PromptValidationError(Exception):
    """Raised when an LLM response fails schema or grounding checks."""

    def __init__(self, message: str, *, raw: str | None = None) -> None:
        super().__init__(message)
        self.raw = raw


def extract_json_payload(text: str) -> Any:
    """Parse JSON from raw model output (fence / think-tag tolerant)."""
    stripped = (text or "").strip()
    if not stripped:
        raise PromptValidationError("Empty LLM response", raw=text)
    stripped = _THINK_RE.sub("", stripped)
    stripped = _THINK_TAG_RE.sub("", stripped).strip()
    if not stripped:
        raise PromptValidationError("Empty LLM response after stripping think tags", raw=text)
    fence = _JSON_FENCE_RE.search(stripped)
    candidates: list[str] = []
    if fence:
        candidates.append(fence.group(1).strip())
    candidates.append(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        candidates.append(stripped[start : end + 1])
    last_error: Exception | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            # Common LLM mistake: invalid \escape sequences in prose.
            repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", candidate)
            if repaired != candidate:
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError as exc2:
                    last_error = exc2
            continue
    raise PromptValidationError(
        f"JSON parse failed: {last_error}", raw=text
    ) from last_error


# Minimum token overlap for OCR-tolerant citation grounding (tier B eligible).
DEFAULT_FUZZY_CITATION_THRESHOLD = 0.85
_CITATION_TOKEN_RE = re.compile(r"[a-z0-9]{2,}", re.I)


def _normalize_for_citation(text: str) -> str:
    text = (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("`", "'")
        .replace("\u00a0", " ")
    )
    return re.sub(r"\s+", " ", text).casefold().strip()


def citation_found_in_document(citation: str, document_text: str) -> bool:
    """True when the verbatim citation appears in the document (whitespace-tolerant)."""
    if not citation or not document_text:
        return False
    cit = _normalize_for_citation(citation)
    doc = _normalize_for_citation(document_text)
    if cit in doc:
        return True
    # Allow minor OCR glue (missing spaces) by removing spaces.
    return cit.replace(" ", "") in doc.replace(" ", "")


def _citation_tokens(text: str) -> list[str]:
    """Accent-stripped tokens for fuzzy OCR citation matching."""
    from utils.strings import normalize, strip_accents

    norm = strip_accents(normalize(text or ""))
    return _CITATION_TOKEN_RE.findall(norm)


def citation_match_quality(
    citation: str,
    document_text: str,
    *,
    min_token_overlap: float = DEFAULT_FUZZY_CITATION_THRESHOLD,
) -> tuple[str, float]:
    """Return ``(kind, score)`` where kind is ``exact``, ``fuzzy``, or ``none``.

    Exact substring (whitespace / space-glue tolerant) scores 1.0. Otherwise a
    sliding-window Jaccard over citation tokens accepts OCR drift when the best
    window overlap is ≥ ``min_token_overlap``.
    """
    if not citation or not document_text:
        return "none", 0.0
    if citation_found_in_document(citation, document_text):
        return "exact", 1.0

    cit_toks = _citation_tokens(citation)
    if len(cit_toks) < 3:
        return "none", 0.0
    doc_toks = _citation_tokens(document_text)
    if not doc_toks:
        return "none", 0.0

    cit_set = frozenset(cit_toks)
    doc_set = frozenset(doc_toks)
    coverage = len(cit_set & doc_set) / len(cit_set) if cit_set else 0.0

    win = max(len(cit_toks), int(len(cit_toks) * 1.5))
    best = coverage
    if len(doc_toks) <= win:
        window = frozenset(doc_toks)
        union = len(cit_set | window)
        best = max(best, (len(cit_set & window) / union) if union else 0.0)
    else:
        step = max(1, win // 4)
        for i in range(0, len(doc_toks) - win + 1, step):
            window = frozenset(doc_toks[i : i + win])
            union = len(cit_set | window)
            score = (len(cit_set & window) / union) if union else 0.0
            if score > best:
                best = score

    best = round(best, 3)
    if best >= min_token_overlap:
        return "fuzzy", best
    return "none", best


def citation_found_in_document_fuzzy(
    citation: str,
    document_text: str,
    *,
    min_token_overlap: float = DEFAULT_FUZZY_CITATION_THRESHOLD,
) -> tuple[bool, float]:
    """True when citation matches exactly or via fuzzy OCR-tolerant overlap."""
    kind, score = citation_match_quality(
        citation, document_text, min_token_overlap=min_token_overlap
    )
    return kind in {"exact", "fuzzy"}, score


def _normalize_analyze_payload(payload: Any) -> Any:
    """Map common LLM field aliases to the canonical analyze schema."""
    if not isinstance(payload, dict):
        return payload
    data = dict(payload)
    if "affirmations" not in data:
        for alt in ("assertions", "claims", "faits", "items"):
            if alt in data and isinstance(data[alt], list):
                data["affirmations"] = data[alt]
                break
    if "document_status" not in data:
        data["document_status"] = "ok"
    raw_claims = data.get("affirmations")
    if isinstance(raw_claims, list):
        normalized: list[dict[str, Any]] = []
        for item in raw_claims:
            if not isinstance(item, dict):
                continue
            claim = dict(item)
            if "citation_exacte" not in claim:
                for key in ("citation", "quote", "extrait", "passage"):
                    if key in claim:
                        claim["citation_exacte"] = claim[key]
                        break
            if "affirmation" not in claim:
                for key in (
                    "text",
                    "texte",
                    "fait",
                    "claim",
                    "assertion",
                    "description",
                    "contenu",
                ):
                    if key in claim:
                        claim["affirmation"] = claim[key]
                        break
            if "theme" not in claim:
                claim["theme"] = claim.get("catégorie") or claim.get("category") or "autre"
            if "niveau_confiance" not in claim:
                conf = claim.get("confiance") or claim.get("confidence") or "moyen"
                claim["niveau_confiance"] = conf
            if "statut" not in claim:
                st = claim.get("status") or claim.get("state") or "confirme_par_le_document"
                claim["statut"] = st
            if "poids_preuve" not in claim and (
                "temoignage" in claim or "sincerite" in claim
            ):
                claim["poids_preuve"] = {
                    "temoignage": claim.get("temoignage") or "indetermine",
                    "sincerite": claim.get("sincerite") or "indetermine",
                }
            # Collapse multi-theme pipes to first token.
            theme = claim.get("theme")
            if isinstance(theme, str) and "|" in theme:
                claim["theme"] = theme.split("|", 1)[0].strip() or "autre"
            # Strip wrapping quotes on citations.
            cit = claim.get("citation_exacte")
            if isinstance(cit, str):
                claim["citation_exacte"] = cit.strip().strip('"').strip("'").strip()
            normalized.append(claim)
        data["affirmations"] = normalized
    if "limites" not in data:
        data["limites"] = str(data.get("limits") or data.get("notes") or "")
    return data


def validate_analyze_response(
    text: str, *, document_text: str
) -> AnalyzeDocumentResult:
    """Validate analyze_document JSON and enforce citation grounding."""
    try:
        payload = _normalize_analyze_payload(extract_json_payload(text))
        result = AnalyzeDocumentResult.model_validate(payload)
    except ValidationError as exc:
        logger.error("analyze_document schema invalid: %s", exc)
        raise PromptValidationError(f"Schema invalid: {exc}", raw=text) from exc

    grounded: list[Affirmation] = []
    for claim in result.affirmations:
        if claim.statut == "confirme_par_le_document":
            kind, score = citation_match_quality(
                claim.citation_exacte, document_text
            )
            if kind == "none":
                from pipeline.quality_report import EXTRACTION_QUALITY

                EXTRACTION_QUALITY.record_citation_match("none")
                logger.warning(
                    "Downgrading claim: citation not found in document "
                    "(best_overlap=%.2f): %r",
                    score,
                    claim.citation_exacte[:120],
                )
                claim = claim.model_copy(update={"statut": "insuffisant"})
            else:
                from pipeline.quality_report import EXTRACTION_QUALITY

                EXTRACTION_QUALITY.record_citation_match(kind)
                affirmation_l = claim.affirmation.casefold()
                citation_l = claim.citation_exacte.casefold()
                if "usine toxique" in affirmation_l and "usine toxique" not in citation_l:
                    raise PromptValidationError(
                        "Overclaim 'usine toxique' without verbatim support",
                        raw=text,
                    )
        grounded.append(claim)

    if result.document_status == "ok" and not any(
        c.statut == "confirme_par_le_document" for c in grounded
    ):
        result = result.model_copy(update={"document_status": "a_revoir_manuellement"})
    return result.model_copy(update={"affirmations": grounded})


def _extract_source_ids(value: Any) -> list[int]:
    """Pull integer source ids from lists, ints, or ``[S:n]`` / digit strings."""
    found: list[int] = []
    if value is None:
        return found
    if isinstance(value, int):
        return [value] if value > 0 else []
    if isinstance(value, list):
        for item in value:
            found.extend(_extract_source_ids(item))
        return sorted(set(found))
    text = str(value)
    for match in re.finditer(r"\[S:([\d,\s]+)\]", text, flags=re.I):
        for part in match.group(1).split(","):
            part = part.strip()
            if part.isdigit():
                found.append(int(part))
    for match in re.finditer(r"\b(\d+)\b", text):
        n = int(match.group(1))
        if 1 <= n <= 9999:
            found.append(n)
    return sorted(set(found))


def _normalize_chronology_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        if isinstance(item, str) and item.strip():
            return {
                "date": "",
                "periode": None,
                "description": item.strip(),
                "sources": [],
            }
        return None
    description = (
        item.get("description")
        or item.get("event")
        or item.get("fait")
        or item.get("texte")
        or item.get("summary")
        or ""
    )
    if not str(description).strip():
        # Free-form single-value dict: use first long string value.
        for key, val in item.items():
            if key.casefold() in {"date", "periode", "period", "sources"}:
                continue
            if isinstance(val, str) and len(val.strip()) > 3:
                description = val
                break
    if not str(description).strip():
        return None
    sources = _extract_source_ids(
        item.get("sources") or item.get("indices_sources") or item.get("refs")
    )
    return {
        "date": str(item.get("date") or item.get("annee") or ""),
        "periode": item.get("periode") or item.get("period") or None,
        "description": str(description).strip(),
        "sources": sources,
    }


def _normalize_verification_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        if isinstance(item, str) and item.strip():
            return {
                "categorie": "general",
                "description": item.strip(),
                "indices_sources": [],
                "priorite": "moyenne",
                "requetes_web_suggerees": [],
            }
        return None
    description = (
        item.get("description")
        or item.get("texte")
        or item.get("point")
        or item.get("question")
        or item.get("gap")
        or ""
    )
    if not str(description).strip():
        for key, val in item.items():
            key_l = key.casefold()
            if key_l.startswith("point") or key_l in {"a_verifier", "vérifier", "verifier"}:
                if isinstance(val, str) and val.strip():
                    description = val
                    break
            if isinstance(val, str) and len(val.strip()) > 10 and key_l not in {
                "categorie",
                "category",
                "priorite",
                "priority",
                "reference",
                "references",
                "sources",
                "indices_sources",
            }:
                description = val
                break
    if not str(description).strip():
        return None
    indices = _extract_source_ids(
        item.get("indices_sources")
        or item.get("sources_indices")
        or item.get("sources")
        or item.get("reference")
        or item.get("references")
        or item.get("refs")
    )
    queries = (
        item.get("requetes_web_suggerees")
        or item.get("requetes_web")
        or item.get("queries")
        or item.get("requete_web")
        or []
    )
    if isinstance(queries, str):
        queries = [queries]
    priorite = str(item.get("priorite") or item.get("priority") or "moyenne").casefold()
    if priorite not in {"haute", "moyenne", "basse"}:
        priorite = "moyenne"
    categorie = str(
        item.get("categorie") or item.get("category") or item.get("theme") or "general"
    )
    return {
        "categorie": categorie.strip() or "general",
        "description": str(description).strip(),
        "indices_sources": indices,
        "priorite": priorite,
        "requetes_web_suggerees": [str(q).strip() for q in queries if str(q).strip()],
    }


def _normalize_sources_par_theme(raw: Any) -> dict[str, list[int]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[int]] = {}
    for theme, ids in raw.items():
        key = str(theme).strip() or "inconnu"
        # Collapse free-form theme labels to a slug-ish token.
        key = re.sub(r"[^a-z0-9_]+", "_", key.casefold()).strip("_") or "inconnu"
        extracted = _extract_source_ids(ids)
        if extracted:
            out[key] = extracted
    return out


def normalize_synthesize_blocks(blocks: dict[str, Any]) -> dict[str, Any]:
    """Map common LLM aliases / messy structures to the canonical schema."""
    data = dict(blocks)
    chrono_raw = data.get("chronologie") or data.get("chronology") or data.get("timeline") or []
    if isinstance(chrono_raw, dict):
        chrono_raw = list(chrono_raw.values())
    chronologie = []
    if isinstance(chrono_raw, list):
        for item in chrono_raw:
            normalized = _normalize_chronology_item(item)
            if normalized:
                chronologie.append(normalized)

    verif_raw = (
        data.get("points_a_verifier")
        or data.get("a_verifier")
        or data.get("verification")
        or data.get("gaps")
        or []
    )
    if isinstance(verif_raw, dict):
        # Either {points: [...]} or {point_1: "...", point_2: "..."}.
        if any(isinstance(v, (dict, list)) for v in verif_raw.values()):
            nested = verif_raw.get("points") or verif_raw.get("items")
            if isinstance(nested, list):
                verif_raw = nested
            else:
                verif_raw = [
                    {"description": v, **({} if not isinstance(v, dict) else v)}
                    if not isinstance(v, dict)
                    else v
                    for k, v in verif_raw.items()
                    if str(k).casefold().startswith("point") or isinstance(v, (dict, str))
                ]
        else:
            verif_raw = [{"description": v} for v in verif_raw.values() if v]
    points: list[dict[str, Any]] = []
    if isinstance(verif_raw, list):
        for item in verif_raw:
            normalized = _normalize_verification_item(item)
            if normalized:
                points.append(normalized)

    themes = _normalize_sources_par_theme(
        data.get("sources_par_theme")
        or data.get("themes")
        or data.get("par_theme")
        or {}
    )
    return {
        "chronologie": chronologie,
        "points_a_verifier": points,
        "sources_par_theme": themes,
    }


def validate_synthesize_blocks(blocks: dict[str, Any]) -> SynthesizeClaimsResult:
    """Validate structured synthesis JSON blocks (alias-tolerant)."""
    normalized = normalize_synthesize_blocks(blocks)
    try:
        return SynthesizeClaimsResult.model_validate(normalized)
    except ValidationError as exc:
        logger.error("synthesize_claims schema invalid: %s", exc)
        raise PromptValidationError(f"Synthesis schema invalid: {exc}") from exc


def _ids_in_s_refs(text: str) -> list[int]:
    found: list[int] = []
    for match in _S_REF_IN_TEXT_RE.finditer(text or ""):
        for part in match.group(1).split(","):
            part = part.strip()
            if part.isdigit():
                found.append(int(part))
    return sorted(set(found))


def _normalize_synthesis_v2_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PromptValidationError("Synthesis output must be a JSON object")
    data = dict(payload)
    # Alias tolerance
    if "faits_etablis" not in data and "facts" in data:
        data["faits_etablis"] = data["facts"]
    if "faits_documentes" not in data:
        for alt in ("faits_documentes_source_unique", "documented_facts", "faits_uniques"):
            if alt in data:
                data["faits_documentes"] = data[alt]
                break
    if "faits_documentes" not in data:
        data["faits_documentes"] = []
    chronologie = data.get("chronologie") or []
    if isinstance(chronologie, list):
        fixed = []
        for item in chronologie:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            if "texte" not in row and "description" in row:
                row["texte"] = row["description"]
            fixed.append(row)
        data["chronologie"] = fixed
    verif = data.get("points_a_verifier") or []
    if isinstance(verif, list):
        fixed_v = []
        for item in verif:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            if "sources_indices" not in row and "indices_sources" in row:
                row["sources_indices"] = row["indices_sources"]
            if "statut" not in row:
                row["statut"] = "à confirmer"
            fixed_v.append(row)
        data["points_a_verifier"] = fixed_v
    if "plan_article" in data and isinstance(data["plan_article"], list):
        data["plan_article"] = [
            item if isinstance(item, str) else str(item.get("titre") or item)
            for item in data["plan_article"]
        ]
    return data


def validate_synthesis_output(
    text: str,
    *,
    grounded_claims: list[Any],
    known_source_ids: set[int],
) -> SynthesisOutput:
    """Validate synthesize_claims v2/v3 JSON against corpus claim/source contracts.

    ``grounded_claims`` items must expose ``claim_id`` and ``source_id``.
    """
    claim_by_id = {c.claim_id: c for c in grounded_claims}
    try:
        payload = _normalize_synthesis_v2_payload(extract_json_payload(text))
        result = SynthesisOutput.model_validate(payload)
    except ValidationError as exc:
        raise PromptValidationError(f"SynthesisOutput schema invalid: {exc}", raw=text) from exc

    errors: list[str] = []

    def _check_forbidden(label: str, body: str) -> None:
        if _FORBIDDEN_REF_RE.search(body):
            errors.append(f"{label}: référence interdite ([0] / [S:0] / [S:?] / [source:…])")
        for match in _BARE_BRACKET_NUM_RE.finditer(body):
            # Allow only if also covered by [S:n] nearby — bare [n] is forbidden.
            errors.append(f"{label}: référence nue interdite {match.group(0)} (exiger [S:n])")

    def _check_fact_list(section: str, facts: list[SynthesisFact]) -> None:
        for idx, fact in enumerate(facts):
            label = f"{section}[{idx}]"
            _check_forbidden(label, fact.texte)
            text_ids = _ids_in_s_refs(fact.texte)
            if not text_ids:
                errors.append(f"{label}: texte sans ancre [S:n]")
            if any(sid <= 0 for sid in fact.sources):
                errors.append(f"{label}: source id <= 0")
            for sid in fact.sources:
                if sid not in known_source_ids:
                    errors.append(f"{label}: source inconnue {sid}")
            if set(text_ids) != set(fact.sources):
                errors.append(
                    f"{label}: [S:n] dans le texte {text_ids} ≠ sources {fact.sources}"
                )
            for cid in fact.claim_ids:
                claim = claim_by_id.get(cid)
                if claim is None:
                    errors.append(f"{label}: claim_id inconnu {cid}")
                    continue
                if claim.source_id not in fact.sources:
                    errors.append(
                        f"{label}: claim {cid} (source {claim.source_id}) "
                        f"absent de sources {fact.sources}"
                    )

    _check_fact_list("faits_etablis", result.faits_etablis)
    _check_fact_list("faits_documentes", result.faits_documentes)

    for idx, event in enumerate(result.chronologie):
        label = f"chronologie[{idx}]"
        _check_forbidden(label, event.texte)
        text_ids = _ids_in_s_refs(event.texte)
        if not text_ids:
            errors.append(f"{label}: texte sans ancre [S:n]")
        if any(sid <= 0 for sid in event.sources):
            errors.append(f"{label}: source id <= 0")
        for sid in event.sources:
            if sid not in known_source_ids:
                errors.append(f"{label}: source inconnue {sid}")
        if set(text_ids) != set(event.sources):
            errors.append(
                f"{label}: [S:n] dans le texte {text_ids} ≠ sources {event.sources}"
            )
        for cid in event.claim_ids:
            claim = claim_by_id.get(cid)
            if claim is None:
                errors.append(f"{label}: claim_id inconnu {cid}")
                continue
            if claim.source_id not in event.sources:
                errors.append(
                    f"{label}: claim {cid} (source {claim.source_id}) "
                    f"absent de sources {event.sources}"
                )

    for idx, point in enumerate(result.points_a_verifier):
        label = f"points_a_verifier[{idx}]"
        _check_forbidden(label, point.description)
        for sid in point.sources_indices:
            if sid <= 0 or sid not in known_source_ids:
                errors.append(f"{label}: source invalide {sid}")

    if errors:
        raise PromptValidationError(
            "Synthèse rejetée — " + "; ".join(errors[:12]),
            raw=text,
        )
    return result


def validate_classify_response(text: str) -> ClassifySourceResult:
    """Validate classify_source JSON."""
    try:
        payload = extract_json_payload(text)
        return ClassifySourceResult.model_validate(payload)
    except ValidationError as exc:
        logger.error("classify_source schema invalid: %s", exc)
        raise PromptValidationError(f"Schema invalid: {exc}", raw=text) from exc


def render_analyze_markdown(result: AnalyzeDocumentResult) -> str:
    """Human Markdown (legacy headings) + embedded JSON for synthesis."""
    confirmed = [
        a for a in result.affirmations if a.statut == "confirme_par_le_document"
    ]
    insufficient = [a for a in result.affirmations if a.statut == "insuffisant"]
    lines: list[str] = [
        "## Idées et faits liés au sujet",
    ]
    if confirmed:
        for claim in confirmed:
            lines.append(
                f"- [{claim.theme} / {claim.niveau_confiance}] {claim.affirmation}"
            )
    else:
        lines.append("- _(aucune affirmation confirmée par le document)_")

    lines.extend(["", "## Passages citables"])
    if confirmed:
        for claim in confirmed:
            lines.append(f'> "{claim.citation_exacte}"')
    else:
        lines.append("- _(pas de citation confirmée)_")

    lines.extend(
        [
            "",
            "## Pertinence pour la recherche",
            (
                f"{len(confirmed)} affirmation(s) confirmée(s), "
                f"{len(insufficient)} insuffisante(s)."
            ),
            "",
            "## Limites de ce document",
            result.limites or "—",
            "",
            "## Affirmations structurées (JSON)",
            "```json",
            result.model_dump_json(indent=2, ensure_ascii=False),
            "```",
        ]
    )
    if result.document_status == "a_revoir_manuellement":
        lines.extend(
            [
                "",
                "> _À revoir manuellement : sortie LLM incomplète ou non probante._",
            ]
        )
    return "\n".join(lines)


def extract_claims_from_llm_ideas(llm_ideas: str | None) -> AnalyzeDocumentResult | None:
    """Pull embedded analyze JSON from a stored LLM ideas block, if present."""
    if not llm_ideas:
        return None
    fence = _JSON_FENCE_RE.search(llm_ideas)
    if not fence:
        return None
    try:
        payload = json.loads(fence.group(1).strip())
        return AnalyzeDocumentResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        return None
