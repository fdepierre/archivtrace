"""Render a `CollectionRun` into the canonical Markdown collection document.

Markdown is the *single business output* of the pipeline. The structure is
intentionally stable and repeatable so it can serve simultaneously as a human
research note, an audit trail and an input for a local LLM / agents.
"""

from __future__ import annotations

from pathlib import Path

from models import (
    CollectedDocument,
    CollectionRun,
    DocumentStatus,
)
from pipeline.markdown_format import (
    EXCERPTS_HEADING,
    format_llm_section,
    format_pending_llm_section,
    llm_count_line,
)
from utils.dates import iso
from utils.files import write_text
from utils.strings import truncate


class MarkdownReporter:
    """Build and persist the Markdown collection file for a run."""

    def __init__(self, *, max_excerpts: int = 5) -> None:
        """Set how many excerpts to keep per document section."""
        self.max_excerpts = max_excerpts

    # -- file naming -----------------------------------------------------
    def filename_for(self, run: CollectionRun) -> str:
        """``{date}_{query}_{connector}_collecte.md``."""
        from utils.research_paths import collecte_filename

        connector = (run.connectors[0] if run.connectors else None) or "unknown"
        return collecte_filename(run.query, connector, when=run.generated_at)

    def write(self, run: CollectionRun, output_dir: Path) -> Path:
        """Render the run and write it to `output_dir`, returning the path."""
        path = output_dir / self.filename_for(run)
        return write_text(path, self.render(run))

    # -- rendering -------------------------------------------------------
    def render(self, run: CollectionRun) -> str:
        """Return the full Markdown document as a string."""
        blocks: list[str] = [
            self._header(run),
            self._metadata(run),
            self._summary(run),
            self._search_params(run),
        ]
        for index, document in enumerate(run.retained, start=1):
            blocks.append(self._document_section(index, document, run))
        blocks.append(self._ignored_section(run))
        blocks.append(self._observations(run))
        blocks.append(self._annexes(run))
        return "\n\n".join(block.strip() for block in blocks if block.strip()) + "\n"

    # -- sections --------------------------------------------------------
    def _header(self, run: CollectionRun) -> str:
        return f"# Collecte de recherche — {run.query}"

    def _metadata(self, run: CollectionRun) -> str:
        return "\n".join(
            [
                "## Métadonnées",
                f"- Query: {run.query}",
                f"- Run ID: {run.run_id}",
                f"- Generated at: {iso(run.generated_at)}",
                f"- Connector(s): {', '.join(run.connectors)}",
                f"- Environment: {run.environment}",
                f"- Root source: {run.root_source}",
                f"- Mode: {'dry-run' if run.dry_run else 'full'}",
            ]
        )

    def _summary(self, run: CollectionRun) -> str:
        return "\n".join(
            [
                "## Résumé de collecte",
                f"- Sources trouvées: {len(run.documents)}",
                f"- Sources retenues: {len(run.retained)}",
                f"- Documents résolus: {run.count_with_status(DocumentStatus.RESOLVED)}",
                f"- Documents téléchargés: {run.count_with_status(DocumentStatus.DOWNLOADED)}",
                f"- Documents avec texte extrait: {run.count_with_status(DocumentStatus.EXTRACTED)}",
                f"- Documents avec matches: {run.documents_with_matches}",
                llm_count_line(run.documents_with_llm_ideas),
            ]
        )

    def _search_params(self, run: CollectionRun) -> str:
        variants = ", ".join(run.keyword_variants) if run.keyword_variants else "—"
        return "\n".join(
            [
                "## Paramètres de recherche",
                f"- Exact keyword: {run.query}",
                f"- Keyword variants: {variants}",
                f"- Match mode: {run.match_mode.value}",
                f"- Context window: {run.context_window} caractères",
            ]
        )

    def _document_section(
        self, index: int, doc: CollectedDocument, run: CollectionRun
    ) -> str:
        title = doc.candidate.title or f"Document {doc.candidate.document_id or index}"
        parts = [f"## Source {index} — {title}"]
        parts.append(self._identity(doc))
        parts.append(self._relevance(doc, run))
        parts.append(self._excerpts(doc))
        parts.append(self._llm_ideas(doc))
        parts.append(self._location(doc))
        parts.append(self._doc_metadata(doc))
        parts.append(self._ocr_notes(doc))
        parts.append(self._technical_notes(doc))
        return "\n\n".join(parts)

    def _identity(self, doc: CollectedDocument) -> str:
        c = doc.candidate
        resolved = doc.resolved
        download = doc.download
        return "\n".join(
            [
                "### Identité",
                f"- Title: {c.title}",
                f"- Connector: {c.connector}",
                f"- Source URL: {c.source_url or '—'}",
                f"- Resolved URL: {(resolved.resolved_url if resolved else None) or '—'}",
                f"- Download URL: {(download.final_url if download else None) or (resolved.download_url if resolved else None) or '—'}",
                f"- Viewer URL: {c.viewer_url or (resolved.viewer_url if resolved else None) or '—'}",
                f"- Document ID: {c.document_id or '—'}",
                f"- Source type: {c.source_type.value}",
                f"- Download strategy: {(resolved.download_strategy if resolved else None) or '—'}",
                f"- Status: {doc.status.value}",
            ]
        )

    def _relevance(self, doc: CollectedDocument, run: CollectionRun) -> str:
        match_type = doc.matches[0].match_type.value if doc.matches else "—"
        return "\n".join(
            [
                "### Pertinence",
                f"- Search keyword: {run.query}",
                f"- Match count: {doc.match_count}",
                f"- Match type: {match_type}",
                f"- Relevance score: {doc.relevance_score}",
                f"- Relevance note: {doc.relevance_note or '—'}",
            ]
        )

    def _excerpts(self, doc: CollectedDocument) -> str:
        lines = [EXCERPTS_HEADING]
        if not doc.matches:
            lines.append("> _Aucun extrait (pas de match ou texte non extrait)._")
            return "\n".join(lines)
        for match in doc.matches[: self.max_excerpts]:
            page = f" _(page {match.page})_" if match.page else ""
            excerpt = truncate(match.excerpt, 400)
            lines.append(f"> {excerpt}{page}")
        if doc.match_count > self.max_excerpts:
            lines.append(f"> … et {doc.match_count - self.max_excerpts} autre(s) extrait(s).")
        return "\n\n".join([lines[0], *lines[1:]])

    def _llm_ideas(self, doc: CollectedDocument) -> str:
        llm = doc.llm_extraction
        if not llm:
            return format_pending_llm_section()
        return format_llm_section(llm)

    def _location(self, doc: CollectedDocument) -> str:
        pages = sorted({m.page for m in doc.matches if m.page is not None})
        page_str = ", ".join(str(p) for p in pages) if pages else "—"
        sections = sorted({m.section for m in doc.matches if m.section}) or ["—"]
        return "\n".join(
            [
                "### Localisation des extraits",
                f"- Page(s): {page_str}",
                f"- Section(s): {', '.join(sections)}",
                "- Coordinates or location if available: —",
            ]
        )

    def _doc_metadata(self, doc: CollectedDocument) -> str:
        meta = doc.candidate.raw_metadata
        return "\n".join(
            [
                "### Métadonnées documentaires",
                f"- Date: {meta.get('date', '—')}",
                f"- Author: {meta.get('author', '—')}",
                f"- Collection: {doc.candidate.collection or meta.get('collection', '—')}",
                f"- Language: {meta.get('language', '—')}",
                f"- Rights: {meta.get('rights', '—')}",
                f"- Archive reference: {doc.candidate.document_id or '—'}",
            ]
        )

    def _ocr_notes(self, doc: CollectedDocument) -> str:
        ext = doc.extracted
        if not ext:
            return "\n".join(
                [
                    "### Notes OCR / extraction",
                    "- OCR required: unknown",
                    "- OCR confidence: —",
                    "- Extraction confidence: —",
                    "- Text quality note: texte non extrait",
                ]
            )
        return "\n".join(
            [
                "### Notes OCR / extraction",
                f"- OCR required: {'yes' if ext.ocr_required else 'no'}",
                f"- OCR confidence: {ext.ocr_confidence if ext.ocr_confidence is not None else '—'}",
                f"- Extraction confidence: {ext.extraction_confidence if ext.extraction_confidence is not None else '—'}",
                f"- Text quality note: {ext.quality_note or '—'} (extractor: {ext.extractor or '—'})",
            ]
        )

    def _technical_notes(self, doc: CollectedDocument) -> str:
        dl = doc.download
        local_file = "—"
        if dl and dl.local_path and dl.local_path.exists():
            try:
                local_file = str(dl.local_path.relative_to(Path.cwd()))
            except ValueError:
                local_file = str(dl.local_path)
        return "\n".join(
            [
                "### Notes techniques",
                f"- Local file: {local_file}",
                f"- HTTP status: {(dl.http_status if dl else None) or '—'}",
                f"- MIME type: {(dl.mime_type if dl else None) or '—'}",
                f"- Error: {(dl.error if dl else None) or '—'}",
                f"- Retry count: {dl.retry_count if dl else 0}",
            ]
        )

    def _ignored_section(self, run: CollectionRun) -> str:
        lines = ["## Sources ignorées ou non exploitables"]
        ignored = run.ignored
        if not ignored:
            lines.append("_Aucune source ignorée._")
            return "\n".join(lines)
        for index, doc in enumerate(ignored, start=1):
            lines.append(f"\n### Source ignorée {index} — {doc.candidate.title}")
            lines.append(f"- Reason ignored: {doc.ignored_reason or '—'}")
            lines.append(f"- URL: {doc.candidate.source_url or doc.candidate.viewer_url or '—'}")
            lines.append(f"- Note: {(doc.resolved.note if doc.resolved else None) or '—'}")
        return "\n".join(lines)

    def _observations(self, run: CollectionRun) -> str:
        lines = ["## Observations globales"]
        if run.observations:
            lines.extend(f"- {obs}" for obs in run.observations)
        else:
            lines.append("- —")
        return "\n".join(lines)

    def _annexes(self, run: CollectionRun) -> str:
        lines = ["## Annexes techniques"]
        if run.annexes:
            lines.extend(f"- {item}" for item in run.annexes)
        else:
            lines.append("- —")
        return "\n".join(lines)
