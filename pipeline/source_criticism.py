"""Deterministic external source criticism (critique externe)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipeline.synthesis_structure import SourceRecord

_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_PHOTO_TYPES = frozenset({"photographie", "photo", "image", "illustration"})
_ORAL_TYPES = frozenset({"mémoire orale", "memoire orale", "témoignage", "temoignage", "oral"})
_PRESS_TYPES = frozenset({"presse", "journal", "périodique", "periodique", "article"})
_REGISTER_TYPES = frozenset({"registre", "cadastre", "acte", "notarial", "recensement"})

# Alerts that force downgrade away from preuve_primaire.
_SEVERE_PREFIXES = (
    "date_anachronique",
    "memoire_orale_date_suspecte",
    "classe_preuve_primaire_a_reexaminer",
)


@dataclass(frozen=True, slots=True)
class ExternalCriticism:
    """Fiche de critique externe for one catalog source."""

    source_id: int
    alerte_critique_externe: list[str]
    temoignage_probable: str  # volontaire | involontaire | indetermine
    provenance_ok: bool
    classe_preuve_suggeree: str | None
    utilisable_suggere: bool | None


def _type_slug(type_document: str | None) -> str:
    return (type_document or "").strip().casefold()


def _years_in(text: str | None) -> list[int]:
    if not text:
        return []
    return [int(y) for y in _YEAR_RE.findall(text)]


def _has_severe(alerts: list[str]) -> bool:
    return any(a.startswith(_SEVERE_PREFIXES) for a in alerts)


def criticise_source(rec: SourceRecord) -> ExternalCriticism:
    """Rule-based external criticism; never invents authenticity proofs."""
    alerts: list[str] = []
    t = _type_slug(rec.type_document)
    years_date = _years_in(rec.date)
    years_period = _years_in(rec.periode_couverte)
    years_title = _years_in(rec.titre)

    connector = (rec.connecteur or "").casefold()
    has_id = bool((rec.cote_ou_identifiant or "").strip() or (rec.url or "").strip())
    provenance_ok = bool(connector) and has_id
    if not connector:
        alerts.append("connecteur_absent")
    if not has_id:
        alerts.append("identifiant_ou_url_absent")

    if t in _PHOTO_TYPES and years_date:
        y = years_date[0]
        if y < 1826:
            alerts.append(f"date_anachronique_pour_photographie:{y}")
    if t in _ORAL_TYPES and years_date and years_date[0] < 1900:
        alerts.append(f"memoire_orale_date_suspecte:{years_date[0]}")

    if years_date and years_period:
        d0, d1 = min(years_date), max(years_date)
        p0, p1 = min(years_period), max(years_period)
        if d1 < p0 - 50 or d0 > p1 + 50:
            alerts.append("date_hors_periode_declaree")

    if years_date and years_title:
        if abs(years_date[0] - years_title[0]) > 150:
            alerts.append("ecart_date_titre")

    if not (rec.auteur_ou_institution or "").strip() and t in _PRESS_TYPES:
        alerts.append("auteur_institution_absent_presse")

    if t in _REGISTER_TYPES or t in {"cadastre"}:
        temoignage = "involontaire"
    elif t in _ORAL_TYPES or t in _PRESS_TYPES or "mémoire" in t or "memoire" in t:
        temoignage = "volontaire"
    elif t in _PHOTO_TYPES:
        temoignage = "involontaire"
    else:
        temoignage = "indetermine"

    # Suggested class: do not keep preuve_primaire when criticism is severe,
    # and upgrade clean archival non_determine → preuve_primaire.
    classe = rec.classe_preuve
    utilisable = rec.utilisable_comme_preuve
    severe = _has_severe(alerts)

    if severe:
        alerts.append("classe_preuve_primaire_a_reexaminer")
        classe = "preuve_secondaire"
        # Still usable as catalog evidence of a title/label, but not primary.
        if utilisable is None:
            utilisable = True
    elif provenance_ok and not alerts:
        if classe in {None, "non_determine"}:
            classe = "preuve_primaire"
        if utilisable is None:
            utilisable = True
    elif provenance_ok and alerts:
        # Soft alerts only.
        if classe in {None, "non_determine", "preuve_primaire"}:
            classe = "preuve_secondaire"
        if utilisable is None:
            utilisable = True
    elif not provenance_ok:
        if classe in {None, "preuve_primaire"}:
            classe = "non_determine"
        if utilisable is None:
            utilisable = False

    return ExternalCriticism(
        source_id=rec.id,
        alerte_critique_externe=sorted(set(alerts)),
        temoignage_probable=temoignage,
        provenance_ok=provenance_ok,
        classe_preuve_suggeree=classe,
        utilisable_suggere=utilisable,
    )


def apply_external_criticism(catalog: list[SourceRecord]) -> list[SourceRecord]:
    """Attach alerts and apply suggested classe_preuve / utilisable flags."""
    out: list[SourceRecord] = []
    for rec in catalog:
        fiche = criticise_source(rec)
        rec.alerte_critique_externe = list(fiche.alerte_critique_externe)
        rec.temoignage_probable = fiche.temoignage_probable
        if fiche.classe_preuve_suggeree is not None:
            rec.classe_preuve = fiche.classe_preuve_suggeree
        if fiche.utilisable_suggere is not None:
            rec.utilisable_comme_preuve = fiche.utilisable_suggere
        if fiche.alerte_critique_externe:
            note = "; ".join(fiche.alerte_critique_externe)
            prev = (rec.justification_preuve or "").strip()
            suffix = f"Critique externe: {note}"
            rec.justification_preuve = f"{prev} | {suffix}" if prev else suffix
        out.append(rec)
    return out
