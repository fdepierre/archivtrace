"""Cross-source corroboration before promoting claims to established facts."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Literal

from pipeline.grounded_claims import (
    GroundedClaimForSynthesis,
    UnverifiedClaimForSynthesis,
)
from pipeline.synthesis_structure import SourceRecord
from utils.strings import normalize, strip_accents

logger = logging.getLogger(__name__)

# Significant token overlap to treat two affirmations as the same fact family.
DEFAULT_JACCARD_THRESHOLD = 0.32
PromotionMode = Literal["tiered", "strict", "all"]
_STOPWORDS = frozenset(
    {
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "de",
        "du",
        "au",
        "aux",
        "et",
        "ou",
        "en",
        "dans",
        "sur",
        "pour",
        "par",
        "avec",
        "sans",
        "ce",
        "cette",
        "ces",
        "qui",
        "que",
        "dont",
        "est",
        "sont",
        "été",
        "etre",
        "a",
        "à",
        "d",
        "l",
        "n",
        "ne",
        "pas",
        "plus",
        "non",
        "ici",
        "se",
        "sa",
        "son",
        "ses",
    }
)
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.I)


@dataclass(frozen=True, slots=True)
class CorroborationCluster:
    """One fact family backed by one or more grounded claims."""

    cluster_id: str
    claims: tuple[GroundedClaimForSynthesis, ...]
    independent_source_ids: tuple[int, ...]
    corroboration_ok: bool
    score_confiance: float


def _tokens(text: str) -> frozenset[str]:
    norm = strip_accents(normalize(text or ""))
    return frozenset(
        t for t in _TOKEN_RE.findall(norm) if t not in _STOPWORDS and len(t) >= 3
    )


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _institution_key(rec: SourceRecord | None) -> str:
    if rec is None:
        return ""
    raw = (rec.auteur_ou_institution or "").strip()
    if not raw:
        return ""
    return strip_accents(normalize(raw))


def sources_are_independent(
    left_id: int,
    right_id: int,
    catalog_by_id: dict[int, SourceRecord],
) -> bool:
    """True when two catalog sources can count as independent witnesses."""
    if left_id == right_id:
        return False
    left = catalog_by_id.get(left_id)
    right = catalog_by_id.get(right_id)
    left_inst = _institution_key(left)
    right_inst = _institution_key(right)
    # Same named author/institution → dependent (false corroboration risk).
    if left_inst and right_inst and left_inst == right_inst:
        return False
    return True


def _cluster_score(claims: list[GroundedClaimForSynthesis], n_independent: int) -> float:
    base = max((c.confidence for c in claims), default=0.5)
    # Extra independent witnesses raise confidence; soft cap at 0.98.
    bonus = 0.12 * max(0, n_independent - 1)
    return min(0.98, round(base + bonus, 3))


def cluster_claims(
    claims: list[GroundedClaimForSynthesis],
    *,
    catalog: list[SourceRecord] | None = None,
    jaccard_threshold: float = DEFAULT_JACCARD_THRESHOLD,
) -> list[CorroborationCluster]:
    """Greedy clustering of similar affirmations (same fact family)."""
    catalog_by_id = {rec.id: rec for rec in (catalog or [])}
    if not claims:
        return []

    token_sets = [_tokens(c.affirmation) for c in claims]
    assigned = [-1] * len(claims)
    clusters_raw: list[list[int]] = []

    for i, claim in enumerate(claims):
        if assigned[i] >= 0:
            continue
        cluster_idx = len(clusters_raw)
        members = [i]
        assigned[i] = cluster_idx
        for j in range(i + 1, len(claims)):
            if assigned[j] >= 0:
                continue
            same_theme = (
                (claim.theme or "").casefold() == (claims[j].theme or "").casefold()
                and bool(claim.theme)
            )
            score = jaccard(token_sets[i], token_sets[j])
            if score >= jaccard_threshold or (same_theme and score >= jaccard_threshold * 0.7):
                assigned[j] = cluster_idx
                members.append(j)
        clusters_raw.append(members)

    result: list[CorroborationCluster] = []
    for idx, members in enumerate(clusters_raw):
        cluster_claims_list = [claims[i] for i in members]
        source_ids = sorted({c.source_id for c in cluster_claims_list})
        independent: list[int] = []
        for sid in source_ids:
            if all(
                sources_are_independent(sid, other, catalog_by_id)
                for other in independent
            ):
                independent.append(sid)
        ok = len(independent) >= 2
        score = _cluster_score(cluster_claims_list, len(independent))
        # Single-source facts stay below the auto-accept band.
        if not ok:
            score = min(score, 0.72)
        annotated = tuple(
            replace(c, score_confiance=score, corroboration_ok=ok)
            for c in cluster_claims_list
        )
        result.append(
            CorroborationCluster(
                cluster_id=f"F-{idx + 1:03d}",
                claims=annotated,
                independent_source_ids=tuple(independent),
                corroboration_ok=ok,
                score_confiance=score,
            )
        )
    return result


def resolve_promotion_mode(
    *,
    promotion_mode: PromotionMode | None = None,
    require_multi_source: bool | None = None,
) -> PromotionMode:
    """Map legacy ``require_multi_source`` to a promotion mode."""
    if promotion_mode is not None:
        return promotion_mode
    if require_multi_source is False:
        return "all"
    if require_multi_source is True:
        return "strict"
    return "tiered"


def apply_corroboration(
    grounded: list[GroundedClaimForSynthesis],
    unverified: list[UnverifiedClaimForSynthesis],
    catalog: list[SourceRecord],
    *,
    require_multi_source: bool | None = None,
    promotion_mode: PromotionMode | None = None,
    jaccard_threshold: float = DEFAULT_JACCARD_THRESHOLD,
) -> tuple[list[GroundedClaimForSynthesis], list[UnverifiedClaimForSynthesis]]:
    """Annotate / split claims by corroboration.

    Modes
    -----
    - ``tiered`` (default): multi-source → ``promotion_tier=corroborated``;
      single-source grounded citations → ``documented`` (still kept for synthesis).
    - ``strict`` (legacy): single-source demoted to unverified
      (``corroboration_insuffisante``).
    - ``all``: every grounded claim treated as corroborated (debug / exploratory).
    """
    mode = resolve_promotion_mode(
        promotion_mode=promotion_mode,
        require_multi_source=require_multi_source,
    )
    # Back-compat: callers that only pass require_multi_source=True expect strict.
    if promotion_mode is None and require_multi_source is True:
        mode = "strict"
    elif promotion_mode is None and require_multi_source is None:
        mode = "tiered"

    clusters = cluster_claims(
        grounded, catalog=catalog, jaccard_threshold=jaccard_threshold
    )
    kept: list[GroundedClaimForSynthesis] = []
    demoted: list[UnverifiedClaimForSynthesis] = list(unverified)

    for cluster in clusters:
        if mode == "strict" and not cluster.corroboration_ok:
            for claim in cluster.claims:
                demoted.append(
                    UnverifiedClaimForSynthesis(
                        claim_id=claim.claim_id,
                        source_id=claim.source_id,
                        source_title=claim.source_title,
                        reason="corroboration_insuffisante",
                        affirmation=claim.affirmation,
                        citation_exacte=claim.citation_exacte,
                        theme=claim.theme,
                    )
                )
            logger.info(
                "Cluster %s demoted (independent sources=%s)",
                cluster.cluster_id,
                cluster.independent_source_ids,
            )
            continue

        for claim in cluster.claims:
            if mode == "all" or cluster.corroboration_ok:
                tier = "corroborated"
                ok = True
                score = (
                    cluster.score_confiance
                    if cluster.corroboration_ok or mode == "all"
                    else min(cluster.score_confiance, 0.72)
                )
                if mode == "all" and not cluster.corroboration_ok:
                    score = min(max(claim.confidence, 0.6), 0.85)
            else:
                # tiered + single source
                tier = "documented"
                ok = False
                score = min(cluster.score_confiance, 0.72)
            kept.append(
                replace(
                    claim,
                    score_confiance=score,
                    corroboration_ok=ok,
                    promotion_tier=tier,
                )
            )

    logger.info(
        "Corroboration (%s): %d claim(s) kept "
        "(%d corroborated, %d documented), %d demoted",
        mode,
        len(kept),
        sum(1 for c in kept if c.promotion_tier == "corroborated"),
        sum(1 for c in kept if c.promotion_tier == "documented"),
        len(demoted) - len(unverified),
    )
    return kept, demoted


def confidence_gate(score: float) -> str:
    """Route by confidence thresholds (auto / alerte / hypotheses)."""
    if score >= 0.85:
        return "auto"
    if score >= 0.60:
        return "alerte"
    return "hypotheses"
