"""Structured synthesis artefacts: source catalog, chronology, themes, verification.

Generated in ``synthesizer.py`` after LLM narrative output. Deterministic helpers
live here; the LLM supplies narrative + optional JSON blocks (chronologie,
points_a_verifier, sources_par_theme) parsed by ``parse_structured_blocks``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from pipeline.markdown_reader import ParsedCollection, ParsedSource

# Canonical theme slugs for cross-site synthesis.
THEME_SLUGS = (
    "cadre_naturel",
    "propriete_fonciere",
    "industrie",
    "risque_hydrologique",
    "patrimoine_architectural",
    "memoire_sociale",
    "presse_medias",
    "toponymie",
    "inconnu",
)

_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_YEAR_RANGE_RE = re.compile(
    r"\b(1[0-9]{3}|20[0-9]{2})\s*[-–—/]\s*(1[0-9]{3}|20[0-9]{2})\b"
)
_CENTURY_RE = re.compile(r"\b(X{1,3}|XIV|XV|XVI|XVII|XVIII|XIX|XX|XXI)(?:e|ème|ᵉ)?\s*si[eè]cle\b", re.I)
_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_SOURCE_REF_RE = re.compile(r"\[S:([\d,\s]+)\]")
# Narrative « Requête web suggérée : … » (piste blocks).
_WEB_QUERY_LINE_RE = re.compile(
    r"(?i)(?:\*\*)?Requête web suggérée(?:\*\*)?\s*:\s*(.+)$",
    re.MULTILINE,
)
# Free-text verification bullets under section 4 / « Pistes encore floues ».
_VERIF_SECTION_RE = re.compile(
    r"(?is)(?:###?\s*4\.\s*)?Pistes encore floues\s*/\s*à vérifier\s*\n+(.*?)(?=\n---|\n###?\s*5\.|\n##\s|\Z)",
)
_VERIF_BULLET_RE = re.compile(
    r"(?m)^\s*[-*]\s+(?:\*\*(.+?)\*\*\s*:?\s*)?(.+)$",
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Chronologie courte Markdown table rows: | date | event | sources |
_CHRONO_ROW_RE = re.compile(
    r"(?m)^\|\s*\*?\*?([^|]+?)\*?\*?\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$",
)

# Theme clusters → French section titles for the suggested article plan.
_THEME_SECTION_SPECS: list[tuple[tuple[str, ...], str]] = [
    (("cadre_naturel", "toponymie"), "Cadre naturel et toponymie"),
    (("propriete_fonciere",), "Propriété foncière et organisation du domaine"),
    (("industrie", "memoire_sociale", "presse_medias"), "Industrialisation, travail et presse"),
    (("risque_hydrologique",), "Crues et gestion du risque hydrologique"),
    (("patrimoine_architectural",), "Patrimoine architectural et mémoire photographique"),
]

_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("industrie", ("usine", "toxique", "garnis", "insalubre", "industrie", "ouvri")),
    ("risque_hydrologique", ("crue", "inond", "hydrolog", "ruisseau")),
    ("propriete_fonciere", ("foncier", "démograph", "demograph", "recensement", "domaine")),
    ("toponymie", ("orthograph", "toponym", "variante")),
    ("patrimoine_architectural", ("château", "chateau", "architect", "photo")),
    ("cadre_naturel", ("nature", "sentier", "botanique", "vallon")),
    ("memoire_sociale", ("mémoire", "memoire", "témoign", "temoign")),
]


@dataclass(slots=True)
class SourceRecord:
    """Normalized metadata for one corpus document (stable synthesis id)."""

    id: int
    titre: str
    type_document: str
    date: str | None
    periode_couverte: str | None
    auteur_ou_institution: str | None
    cote_ou_identifiant: str | None
    url: str | None
    connecteur: str | None = None
    themes: list[str] = field(default_factory=list)
    # Additive: probative classification (heuristic / classify_source).
    classe_preuve: str | None = None
    utilisable_comme_preuve: bool | None = None
    justification_preuve: str | None = None
    # External criticism (deterministic rules in source_criticism.py).
    alerte_critique_externe: list[str] = field(default_factory=list)
    temoignage_probable: str | None = None


@dataclass(slots=True)
class ChronologyEntry:
    """One dated event in the structured synthesis chronology."""

    date: str
    periode: str | None
    description: str
    sources: list[int]


@dataclass(slots=True)
class VerificationPoint:
    """A claim or gap flagged for further archival or web research."""

    categorie: str
    description: str
    indices_sources: list[int]
    priorite: str
    requetes_web_suggerees: list[str] = field(default_factory=list)
    id: str = ""


@dataclass(slots=True)
class ReferenceControl:
    """Coherence check between catalog ids and ``[S:n]`` anchors in the body."""

    sources_utilisees: list[int] = field(default_factory=list)
    sources_non_utilisees: list[int] = field(default_factory=list)
    references_inconnues: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ArticlePlanSection:
    """One suggested chapter of a historical article outline."""

    titre: str
    themes: list[str] = field(default_factory=list)
    sources: list[int] = field(default_factory=list)
    periode: str | None = None


@dataclass(slots=True)
class StructuredSynthesisData:
    """Machine-readable blocks appended to synthesis Markdown."""

    sources: list[SourceRecord] = field(default_factory=list)
    chronologie: list[ChronologyEntry] = field(default_factory=list)
    points_a_verifier: list[VerificationPoint] = field(default_factory=list)
    sources_par_theme: dict[str, list[int]] = field(default_factory=dict)
    reference_control: ReferenceControl | None = None
    plan_article: list[ArticlePlanSection] = field(default_factory=list)
    recherches_web: list[str] = field(default_factory=list)


def format_source_refs(source_ids: list[int]) -> str:
    """Format stable source anchors for narrative text: ``[S:1,3,21]``."""
    unique = sorted({i for i in source_ids if i > 0})
    if not unique:
        return ""
    return f"[S:{','.join(str(i) for i in unique)}]"


def parse_source_refs(text: str) -> list[int]:
    """Extract all ``[S:…]`` ids from narrative Markdown."""
    found: list[int] = []
    for match in _SOURCE_REF_RE.finditer(text):
        for part in match.group(1).split(","):
            part = part.strip()
            if part.isdigit():
                found.append(int(part))
    return sorted(set(found))


def build_source_catalog(collection: ParsedCollection) -> list[SourceRecord]:
    """Normalize per-source metadata from parsed collecte Markdown."""
    from pipeline.source_classifier import classify_source_heuristic
    from pipeline.source_criticism import apply_external_criticism

    catalog: list[SourceRecord] = []
    for source in collection.sources:
        sid = source.index
        excerpt_blob = " ".join(source.excerpts)
        llm_blob = source.llm_ideas or ""
        blob = f"{source.title} {excerpt_blob} {llm_blob}"
        date = normalize_date(source.date, blob)
        periode = infer_period_label(date, blob)
        themes = infer_themes(source)
        preuve = classify_source_heuristic(
            title=source.title,
            url=source.source_url,
            connector=source.connector,
            source_type=source.source_type,
        )
        catalog.append(
            SourceRecord(
                id=sid,
                titre=source.title,
                type_document=infer_document_type(source),
                date=date,
                periode_couverte=periode,
                auteur_ou_institution=normalize_optional(source.author),
                cote_ou_identifiant=infer_cote(source, excerpt_blob),
                url=source.source_url,
                connecteur=source.connector,
                themes=themes,
                classe_preuve=preuve.classe if preuve else None,
                utilisable_comme_preuve=(
                    preuve.utilisable_comme_preuve if preuve else None
                ),
                justification_preuve=preuve.justification if preuve else None,
            )
        )
    return apply_external_criticism(catalog)


def infer_document_type(source: ParsedSource) -> str:
    """Heuristic document type from title, source_type and connector."""
    title = source.title.lower()
    blob = f"{title} {' '.join(source.excerpts)}".lower()
    st = (source.source_type or "").lower()
    if any(k in blob for k in ("recensement", "registre", "6 m ", "6m")):
        return "registre"
    if st == "periodical" or any(
        k in title for k in ("journal", " n°", " n ", " pp.", "presse", "per00", "per0")
    ):
        return "presse"
    if any(k in blob for k in ("étude", "etude", "sitolog", "rapport", "diagnostic")):
        return "étude technique"
    if "carte postale" in title or ("carte" in title and st == "image"):
        return "carte postale"
    if st == "image" or "11fi" in title:
        return "photographie"
    if "album" in title or "photo" in title:
        return "photographie"
    if "mémoire orale" in title or "oral" in title.lower():
        return "mémoire orale"
    if st == "manuscript":
        return "archives"
    if st:
        return st
    return "document"


def normalize_date(explicit: str | None, blob: str) -> str | None:
    """Return YYYY, YYYY-YYYY, or None."""
    if explicit and explicit.strip() not in ("—", "None", "none", ""):
        cleaned = explicit.strip()
        if _YEAR_RE.search(cleaned):
            return cleaned
    range_match = _YEAR_RANGE_RE.search(blob)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}"
    years = _YEAR_RE.findall(blob)
    if years:
        return years[0]
    return None


def infer_period_label(date: str | None, blob: str) -> str | None:
    """Human period label (century or date range)."""
    if date and "-" in date:
        return date
    century = _CENTURY_RE.search(blob)
    if century:
        return f"{century.group(1).upper()}e siècle"
    if date and len(date) == 4:
        year = int(date)
        if year < 1500:
            return "Moyen Âge / début période moderne"
        if year < 1800:
            return "Ancien Régime"
        if year < 1900:
            return "XIXe siècle"
        if year < 2000:
            return "XXe siècle"
        return "XXIe siècle"
    return None


def infer_cote(source: ParsedSource, excerpt_blob: str) -> str | None:
    """Archive shelf mark or internal id."""
    if source.archive_reference and source.archive_reference not in ("—", "None"):
        return source.archive_reference
    if source.document_id:
        return source.document_id
    # Excerpt pattern: "ROCHECARDON … 6 M 75 · 1846"
    cote_match = re.search(r"\b(\d+\s*[A-Z]\s*\d+(?:/\d+)*)\b", excerpt_blob)
    if cote_match:
        return cote_match.group(1)
    return None


def normalize_optional(value: str | None) -> str | None:
    """Return stripped text, or None for empty / placeholder values."""
    if not value or value.strip() in ("—", "None", "none", ""):
        return None
    return value.strip()


def infer_themes(source: ParsedSource) -> list[str]:
    """Keyword-based theme assignment (deterministic fallback)."""
    blob = f"{source.title} {' '.join(source.excerpts)} {source.llm_ideas or ''}".lower()
    themes: list[str] = []
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("cadre_naturel", ("sentier", "botanique", "vallon", "ruisseau", "nature", "paysage")),
        ("propriete_fonciere", ("domaine", "chapitre", "soumission", "foncier", "recensement", "cote")),
        ("industrie", ("usine", "garnis", "insalubre", "ouvri", "industr")),
        ("risque_hydrologique", ("crue", "hydrolog", "sitolog", "inond")),
        ("patrimoine_architectural", ("château", "chateau", "carte postale", "album", "photo", "église", "eglise")),
        ("memoire_sociale", ("mémoire orale", "memoire orale", "témoignage", "temoignage", "oral")),
        ("presse_medias", ("journal", " n°", "presse", " illustr")),
        ("toponymie", ("vallon de", "toponym", "lieu-dit", "rochecardon")),
    ]
    for slug, keywords in rules:
        if any(k in blob for k in keywords):
            themes.append(slug)
    return themes or ["inconnu"]


def build_sources_by_theme(catalog: list[SourceRecord]) -> dict[str, list[int]]:
    """Aggregate source ids per theme slug."""
    by_theme: dict[str, list[int]] = {slug: [] for slug in THEME_SLUGS}
    for record in catalog:
        for theme in record.themes:
            key = theme if theme in by_theme else "inconnu"
            if record.id not in by_theme[key]:
                by_theme[key].append(record.id)
    # Drop empty buckets except keep all keys user asked for
    return {k: sorted(v) for k, v in by_theme.items() if v}


def parse_structured_blocks(body: str) -> tuple[str, dict[str, Any]]:
    """Split LLM body into narrative Markdown and parsed JSON blocks."""
    blocks: dict[str, Any] = {}
    narrative = body
    key_aliases = {
        "chronologie": "chronologie",
        "chronology": "chronologie",
        "timeline": "chronologie",
        "points_a_verifier": "points_a_verifier",
        "a_verifier": "points_a_verifier",
        "verification": "points_a_verifier",
        "gaps": "points_a_verifier",
        "sources_par_theme": "sources_par_theme",
        "themes": "sources_par_theme",
        "par_theme": "sources_par_theme",
        "sources": "sources",
    }

    def _ingest(data: Any) -> None:
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            canon = key_aliases.get(str(key).casefold())
            if canon:
                blocks[canon] = value

    for match in _JSON_FENCE_RE.finditer(body):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _ingest(data)
        narrative = narrative.replace(match.group(0), "").strip()

    # Fallback: unfenced JSON objects containing known keys.
    if not blocks:
        for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", body, re.DOTALL):
            raw = match.group(0)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            before = len(blocks)
            _ingest(data)
            if len(blocks) > before:
                narrative = narrative.replace(raw, "").strip()

    return narrative, blocks


def chronology_from_json(raw: list[Any]) -> list[ChronologyEntry]:
    """Parse LLM chronology JSON into ChronologyEntry objects."""
    entries: list[ChronologyEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        sources = item.get("sources") or []
        if isinstance(sources, list):
            ids = [int(s) for s in sources if str(s).isdigit()]
        else:
            ids = []
        entries.append(
            ChronologyEntry(
                date=str(item.get("date") or ""),
                periode=item.get("periode") or item.get("period") or None,
                description=str(item.get("description") or "").strip(),
                sources=ids,
            )
        )
    return [e for e in entries if e.description]


def verification_from_json(raw: list[Any]) -> list[VerificationPoint]:
    """Parse LLM verification-points JSON into VerificationPoint objects."""
    points: list[VerificationPoint] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        src = (
            item.get("sources_indices")
            or item.get("indices_sources")
            or item.get("sources")
            or []
        )
        if isinstance(src, list):
            ids = [int(s) for s in src if str(s).isdigit()]
        else:
            ids = parse_source_refs(str(src))
        queries = item.get("requetes_web_suggerees") or item.get("requetes_web") or []
        if isinstance(queries, str):
            queries = [queries]
        description = str(item.get("description") or "").strip()
        categorie = str(item.get("categorie") or item.get("category") or "general")
        priorite = str(item.get("priorite") or item.get("priority") or "moyenne")
        point_id = str(item.get("id") or "").strip() or make_verification_id(
            categorie, description
        )
        points.append(
            VerificationPoint(
                id=point_id,
                categorie=categorie,
                description=description,
                indices_sources=ids,
                priorite=priorite,
                requetes_web_suggerees=[str(q).strip(" \"'`") for q in queries if q],
            )
        )
    return [p for p in points if p.description]


def make_verification_id(categorie: str, description: str) -> str:
    """Build a stable slug id: ``categorie_mots_cles`` (max ~60 chars)."""
    year = _YEAR_RE.search(description)
    year_suffix = f"_{year.group(1)}" if year else ""
    words = _SLUG_RE.sub("_", description.lower()).strip("_")
    words = "_".join(w for w in words.split("_") if w)[:40].strip("_")
    cat = _SLUG_RE.sub("_", categorie.lower()).strip("_") or "point"
    return f"{cat}_{words}{year_suffix}"[:72].strip("_")


def infer_verification_category(text: str) -> str:
    """Infer a theme category from verification bullet wording."""
    lower = text.lower()
    for categorie, keywords in _CATEGORY_KEYWORDS:
        if any(k in lower for k in keywords):
            return categorie
    return "general"


def infer_verification_priority(text: str) -> str:
    """Heuristic priority: haute if industrial/identity gap, else moyenne/basse."""
    lower = text.lower()
    if any(k in lower for k in ("usine", "toxique", "identification exacte", "nom commercial")):
        return "haute"
    if any(k in lower for k in ("manque", "pas clairement", "reste à", "flou")):
        return "moyenne"
    return "basse"


def extract_chronology_from_narrative(narrative: str) -> list[ChronologyEntry]:
    """Parse « Chronologie courte » Markdown table rows when LLM JSON is missing."""
    if "Chronologie" not in narrative:
        return []
    entries: list[ChronologyEntry] = []
    for match in _CHRONO_ROW_RE.finditer(narrative):
        date_cell = match.group(1).strip()
        desc_cell = match.group(2).strip()
        src_cell = match.group(3).strip()
        if date_cell.lower().startswith("période") or date_cell.lower() == "date":
            continue
        if set(date_cell) <= {":", "-", " "}:
            continue
        date_clean = re.sub(r"[*_`]", "", date_cell).strip()
        desc_clean = re.sub(r"\s+", " ", re.sub(r"\[S:[^\]]+\]", "", desc_cell)).strip()
        if not desc_clean or len(desc_clean) < 8:
            continue
        entries.append(
            ChronologyEntry(
                date=date_clean,
                periode=infer_period_label(None, date_clean) or date_clean,
                description=desc_clean,
                sources=parse_source_refs(src_cell + " " + desc_cell),
            )
        )
    return entries


def extract_verification_points_from_narrative(narrative: str) -> list[VerificationPoint]:
    """Parse free-text « Pistes encore floues » bullets into VerificationPoint list.

    Output format matches the structured JSON block (id, categorie, description,
    sources_indices via indices_sources, priorite, requetes_web_suggerees).
    """
    section_match = _VERIF_SECTION_RE.search(narrative)
    if not section_match:
        return []
    block = section_match.group(1)
    points: list[VerificationPoint] = []
    for bullet in _VERIF_BULLET_RE.finditer(block):
        title = (bullet.group(1) or "").strip()
        body = (bullet.group(2) or "").strip()
        description = f"{title}: {body}".strip(": ").strip() if title else body
        description = re.sub(r"\s+", " ", description).strip()
        if len(description) < 12:
            continue
        categorie = infer_verification_category(description)
        source_ids = parse_source_refs(description)
        queries = suggest_web_queries_for_gap(description, title)
        points.append(
            VerificationPoint(
                id=make_verification_id(categorie, title or description),
                categorie=categorie,
                description=description,
                indices_sources=source_ids,
                priorite=infer_verification_priority(description),
                requetes_web_suggerees=queries,
            )
        )
    return points


def suggest_web_queries_for_gap(description: str, title: str = "") -> list[str]:
    """Propose 1–2 Google/Gallica-style queries from a verification bullet."""
    seed = title or description
    seed = re.sub(r"\[S:[^\]]+\]", "", seed)
    seed = re.sub(r"[*:`]", "", seed).strip()
    fragment = seed.split(":")[0].strip()[:90].strip(" .;:")
    if not fragment:
        return []
    years = _YEAR_RE.findall(description)
    year_bit = f" {years[0]}" if years else ""
    queries = [
        f'"{fragment}"{year_bit}'.strip(),
        f"{fragment} Rochecardon archives{year_bit}".strip(),
    ]
    return dedupe_web_queries(queries)


def check_reference_coherence(
    catalog: list[SourceRecord],
    *text_parts: str,
) -> ReferenceControl:
    """Compare catalog ids (1..N) with ``[S:n]`` ids found in narrative texts.

    Returns sources_non_utilisees / references_inconnues for the control section.
    """
    known_ids = {rec.id for rec in catalog}
    used: set[int] = set()
    for part in text_parts:
        if part:
            used.update(parse_source_refs(part))
    return ReferenceControl(
        sources_utilisees=sorted(used & known_ids),
        sources_non_utilisees=sorted(known_ids - used),
        references_inconnues=sorted(used - known_ids),
    )


def extract_web_queries_from_narrative(narrative: str) -> list[str]:
    """Collect « Requête web suggérée » lines from piste blocks in the narrative."""
    queries: list[str] = []
    for match in _WEB_QUERY_LINE_RE.finditer(narrative):
        raw = match.group(1).strip().strip("*").strip()
        # Split OR-joined alternatives into separate queries when useful.
        parts = re.split(r"\s+OR\s+", raw, flags=re.IGNORECASE)
        for part in parts:
            cleaned = part.strip().strip(" \"'`.,;")
            if cleaned:
                queries.append(cleaned)
    return queries


def dedupe_web_queries(queries: list[str]) -> list[str]:
    """Deduplicate web queries (case-insensitive), preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for query in queries:
        key = re.sub(r"\s+", " ", query.strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(query.strip())
    return result


def collect_web_queries(
    narrative: str,
    points: list[VerificationPoint],
) -> list[str]:
    """Merge piste queries + verification queries into one deduplicated list."""
    pooled: list[str] = extract_web_queries_from_narrative(narrative)
    for point in points:
        pooled.extend(point.requetes_web_suggerees)
    return dedupe_web_queries(pooled)


def period_hint_for_themes(
    themes: list[str],
    chronologie: list[ChronologyEntry],
    catalog: list[SourceRecord],
) -> str | None:
    """Pick a period label from chronology or catalog dates matching theme sources."""
    theme_source_ids: set[int] = set()
    for rec in catalog:
        if any(t in rec.themes for t in themes):
            theme_source_ids.add(rec.id)
    for entry in chronologie:
        if theme_source_ids & set(entry.sources):
            return entry.periode or entry.date or None
    dates = [rec.date for rec in catalog if rec.id in theme_source_ids and rec.date]
    if dates:
        return dates[0]
    return None


def build_article_plan(
    sources_par_theme: dict[str, list[int]],
    chronologie: list[ChronologyEntry],
    catalog: list[SourceRecord],
    query: str = "",
) -> list[ArticlePlanSection]:
    """Build a historical article outline from themes + chronology (not hard-coded).

    Only emits sections whose themes actually appear in ``sources_par_theme``.
    """
    present = {theme for theme, ids in sources_par_theme.items() if ids and theme != "inconnu"}
    sections: list[ArticlePlanSection] = []
    used_themes: set[str] = set()
    for theme_group, base_title in _THEME_SECTION_SPECS:
        active = [t for t in theme_group if t in present]
        if not active:
            continue
        source_ids: list[int] = []
        for theme in active:
            for sid in sources_par_theme.get(theme, []):
                if sid not in source_ids:
                    source_ids.append(sid)
        periode = period_hint_for_themes(active, chronologie, catalog)
        title = base_title
        if query and query.lower() not in title.lower():
            # Keep titles generic; period goes in the bullet, not forced into title.
            pass
        if periode:
            title = f"{base_title} ({periode})"
        sections.append(
            ArticlePlanSection(
                titre=title,
                themes=active,
                sources=source_ids[:12],
                periode=periode,
            )
        )
        used_themes.update(active)
    leftover = sorted(present - used_themes)
    if leftover:
        ids: list[int] = []
        for theme in leftover:
            ids.extend(sources_par_theme.get(theme, []))
        sections.append(
            ArticlePlanSection(
                titre="Autres angles documentaires",
                themes=leftover,
                sources=sorted(set(ids))[:12],
                periode=None,
            )
        )
    return sections


def enrich_structured_from_narrative(
    data: StructuredSynthesisData,
    narrative: str,
    *,
    query: str = "",
) -> StructuredSynthesisData:
    """Fill verification / plan / web / reference-control from narrative + catalog.

    Deterministic post-pass so historical workflows work even when the LLM omitted JSON.
    """
    if not data.chronologie:
        data.chronologie = extract_chronology_from_narrative(narrative)

    if not data.points_a_verifier:
        data.points_a_verifier = extract_verification_points_from_narrative(narrative)
    else:
        # Ensure every LLM point has a stable id.
        for point in data.points_a_verifier:
            if not point.id:
                point.id = make_verification_id(point.categorie, point.description)
            if not point.requetes_web_suggerees:
                point.requetes_web_suggerees = suggest_web_queries_for_gap(point.description)

    # Attach theme-related source ids when a verification bullet omitted [S:n].
    for point in data.points_a_verifier:
        if point.indices_sources:
            continue
        theme_ids = data.sources_par_theme.get(point.categorie) or []
        point.indices_sources = list(theme_ids[:5])

    data.recherches_web = collect_web_queries(narrative, data.points_a_verifier)
    data.plan_article = build_article_plan(
        data.sources_par_theme,
        data.chronologie,
        data.sources,
        query=query,
    )
    # Include chronology + verification refs in the coherence scan.
    extra_parts = [
        narrative,
        " ".join(format_source_refs(e.sources) for e in data.chronologie),
        " ".join(format_source_refs(p.indices_sources) for p in data.points_a_verifier),
    ]
    data.reference_control = check_reference_coherence(data.sources, *extra_parts)
    return data


def verification_point_as_dict(point: VerificationPoint) -> dict[str, Any]:
    """Serialize a verification point with ``sources_indices`` alias for scripts."""
    return {
        "id": point.id,
        "categorie": point.categorie,
        "description": point.description,
        "sources_indices": point.indices_sources,
        "indices_sources": point.indices_sources,
        "requetes_web_suggerees": point.requetes_web_suggerees,
        "priorite": point.priorite,
    }


def merge_structured_data(
    catalog: list[SourceRecord],
    llm_blocks: dict[str, Any],
) -> StructuredSynthesisData:
    """Combine deterministic catalog with optional LLM JSON blocks."""
    chronologie = chronology_from_json(llm_blocks.get("chronologie") or [])
    points = verification_from_json(llm_blocks.get("points_a_verifier") or [])
    by_theme = build_sources_by_theme(catalog)
    llm_themes = llm_blocks.get("sources_par_theme")
    if isinstance(llm_themes, dict):
        for key, ids in llm_themes.items():
            if not isinstance(ids, list):
                continue
            normalized = sorted({int(i) for i in ids if str(i).isdigit()})
            if normalized:
                by_theme[key] = sorted(set(by_theme.get(key, []) + normalized))
    return StructuredSynthesisData(
        sources=catalog,
        chronologie=chronologie,
        points_a_verifier=points,
        sources_par_theme=by_theme,
    )


def render_source_catalog_markdown(catalog: list[SourceRecord]) -> str:
    """Human-readable detailed source table."""
    lines = [
        "## Corpus documentaire (métadonnées détaillées)",
        "",
        "| Id | Titre | Type | Date | Période | Auteur / institution | Cote / id | Connecteur |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for rec in catalog:
        lines.append(
            "| {id} | {titre} | {type} | {date} | {periode} | {auteur} | {cote} | {conn} |".format(
                id=rec.id,
                titre=rec.titre.replace("|", "\\|")[:80],
                type=rec.type_document,
                date=rec.date or "—",
                periode=(rec.periode_couverte or "—")[:40],
                auteur=(rec.auteur_ou_institution or "—")[:40],
                cote=(rec.cote_ou_identifiant or "—")[:30],
                conn=rec.connecteur or "—",
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_source_catalog_json(catalog: list[SourceRecord]) -> str:
    """Emit the source catalog as a labeled Markdown JSON fence."""
    payload = {"sources": [asdict(r) for r in catalog]}
    return _json_block("sources", payload["sources"])


def render_chronology_table(entries: list[ChronologyEntry]) -> str:
    """Render chronology entries as a human-readable Markdown table."""
    if not entries:
        return ""
    lines = [
        "## Chronologie structurée (tableau)",
        "",
        "| Date | Période | Description | Sources |",
        "|---|---|---|---|",
    ]
    for entry in entries:
        refs = format_source_refs(entry.sources) or "—"
        desc = entry.description.replace("|", "\\|")
        lines.append(
            f"| {entry.date or '—'} | {entry.periode or '—'} | {desc} | {refs} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_chronology_json(entries: list[ChronologyEntry]) -> str:
    """Emit chronology entries as a labeled Markdown JSON fence."""
    if not entries:
        return ""
    payload = [
        {
            "date": e.date,
            "periode": e.periode,
            "description": e.description,
            "sources": e.sources,
        }
        for e in entries
    ]
    return _json_block("chronologie", payload)


def render_verification_json(points: list[VerificationPoint]) -> str:
    """Emit verification points as a labeled Markdown JSON fence."""
    if not points:
        return ""
    payload = [verification_point_as_dict(p) for p in points]
    return _json_block("points_a_verifier", payload)


def render_verification_markdown(points: list[VerificationPoint]) -> str:
    """Render verification points as a human-readable Markdown section."""
    if not points:
        return ""
    lines = ["## Points à vérifier (recherche complémentaire)", ""]
    for point in points:
        refs = format_source_refs(point.indices_sources)
        heading = point.id or point.categorie
        lines.append(f"### {heading} ({point.priorite})")
        lines.append(point.description)
        lines.append(f"- Catégorie : {point.categorie}")
        if refs:
            lines.append(f"- Indices archive : {refs}")
        if point.requetes_web_suggerees:
            lines.append("- Requêtes web suggérées :")
            for q in point.requetes_web_suggerees:
                lines.append(f"  - `{q}`")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_sources_by_theme_json(by_theme: dict[str, list[int]]) -> str:
    """Emit theme→source-id map as a labeled Markdown JSON fence."""
    if not by_theme:
        return ""
    return _json_block("sources_par_theme", by_theme)


def render_sources_by_theme_markdown(by_theme: dict[str, list[int]]) -> str:
    """Render theme→source-id map as a Markdown bullet list."""
    if not by_theme:
        return ""
    lines = ["## Sources par thème", ""]
    for theme, ids in sorted(by_theme.items()):
        if not ids:
            continue
        lines.append(f"- **{theme}** : {format_source_refs(ids)}")
    lines.append("")
    return "\n".join(lines)


def render_article_plan_markdown(sections: list[ArticlePlanSection]) -> str:
    """Render suggested historical article outline (human-readable)."""
    if not sections:
        return ""
    lines = ["## Plan d’article suggéré", ""]
    for index, section in enumerate(sections, start=1):
        lines.append(f"{index}. {section.titre}")
        theme_list = ", ".join(section.themes)
        refs = format_source_refs(section.sources)
        bullet = f"   - Sources principales : thèmes {theme_list}"
        if refs:
            bullet += f", {refs}"
        lines.append(bullet)
        if section.periode:
            lines.append(f"   - Période indicative : {section.periode}")
    lines.append("")
    return "\n".join(lines)


def render_article_plan_json(sections: list[ArticlePlanSection]) -> str:
    """Emit article plan as a labeled Markdown JSON fence."""
    if not sections:
        return ""
    payload = [
        {
            "titre": s.titre,
            "themes": s.themes,
            "sources": s.sources,
            "periode": s.periode,
        }
        for s in sections
    ]
    return _json_block("plan_article", payload)


def render_web_research_markdown(queries: list[str]) -> str:
    """Centralize all suggested web queries for later automated search."""
    if not queries:
        return ""
    lines = [
        "## Recherches web à lancer",
        "",
        "Liste dédupliquée (pistes + points à vérifier).",
        "",
    ]
    for query in queries:
        lines.append(f"- `{query}`")
    lines.append("")
    return "\n".join(lines)


def render_web_research_json(queries: list[str]) -> str:
    """Emit centralized web queries as a labeled Markdown JSON fence."""
    if not queries:
        return ""
    return _json_block("recherches_web_a_lancer", queries)


def render_reference_control_markdown(control: ReferenceControl) -> str:
    """Human-readable coherence check for ``[S:n]`` anchors vs catalog."""
    lines = [
        "## Contrôle des références",
        "",
        f"- Sources citées dans le texte : {len(control.sources_utilisees)}",
        f"- Sources non utilisées : {len(control.sources_non_utilisees)}",
        f"- Références inconnues : {len(control.references_inconnues)}",
        "",
    ]
    if control.sources_non_utilisees:
        lines.append(
            f"- `sources_non_utilisees` : {format_source_refs(control.sources_non_utilisees)}"
        )
    else:
        lines.append("- `sources_non_utilisees` : _(aucune)_")
    if control.references_inconnues:
        lines.append(
            f"- `references_inconnues` : {format_source_refs(control.references_inconnues)}"
        )
    else:
        lines.append("- `references_inconnues` : _(aucune)_")
    lines.append("")
    return "\n".join(lines)


def render_reference_control_json(control: ReferenceControl) -> str:
    """Emit reference coherence check as a labeled Markdown JSON fence."""
    payload = {
        "sources_utilisees": control.sources_utilisees,
        "sources_non_utilisees": control.sources_non_utilisees,
        "references_inconnues": control.references_inconnues,
    }
    return _json_block("controle_references", payload)


def render_references_enriched(catalog: list[SourceRecord]) -> str:
    """Full proof list with ids and metadata (human section)."""
    lines = [
        "## Références documentaires (preuves)",
        "",
        "Inventaire **complet** du corpus fusionné. Les ids ``S:n`` servent d'ancres",
        "dans le texte narratif (`[S:1,3]`).",
        "",
    ]
    for rec in catalog:
        lines.append(f"### [S:{rec.id}] {rec.titre}")
        lines.append(f"- Type : {rec.type_document}")
        if rec.date:
            lines.append(f"- Date : {rec.date}")
        if rec.periode_couverte:
            lines.append(f"- Période couverte : {rec.periode_couverte}")
        if rec.auteur_ou_institution:
            lines.append(f"- Auteur / institution : {rec.auteur_ou_institution}")
        if rec.cote_ou_identifiant:
            lines.append(f"- Cote / identifiant : {rec.cote_ou_identifiant}")
        if rec.connecteur:
            lines.append(f"- Site / connecteur : {rec.connecteur}")
        if rec.themes:
            lines.append(f"- Thèmes : {', '.join(rec.themes)}")
        if rec.classe_preuve:
            utilisable = (
                "oui" if rec.utilisable_comme_preuve else "non"
                if rec.utilisable_comme_preuve is not None
                else "—"
            )
            lines.append(
                f"- Classe preuve : {rec.classe_preuve} (utilisable={utilisable})"
            )
            if rec.justification_preuve:
                lines.append(f"- Justification preuve : {rec.justification_preuve}")
        if rec.temoignage_probable:
            lines.append(f"- Témoignage probable : {rec.temoignage_probable}")
        if rec.alerte_critique_externe:
            lines.append(
                "- Alerte critique externe : "
                + "; ".join(rec.alerte_critique_externe)
            )
        if rec.url:
            lines.append(f"- URL : {rec.url}")
        else:
            lines.append("- URL : _(non disponible)_")
        lines.append("")
    return "\n".join(lines).rstrip()


def _json_block(label: str, payload: Any) -> str:
    """Wrap `payload` in a labeled Markdown heading and JSON fence."""
    return (
        f"## Données structurées — {label}\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n"
    )
