"""Collect and analyse in one process, resuming the latest notebook."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from dataclasses import replace

from config import Config
from connectors import build_connector
from models import CollectedDocument, ExtractedText, LlmExtraction
from pipeline.collector import Collector
from pipeline.keyword_matcher import KeywordMatcher
from pipeline.live_analyse import AnalysisJob, AnalysisLane
from pipeline.markdown_patcher import patch_collection_markdown
from pipeline.markdown_reader import read_collection
from pipeline.markdown_reporter import MarkdownReporter
from pipeline.text_extractor import TextExtractor
from utils.analyse_paths import (
    annotate_analyse_metadata,
    derive_analyse_output_path,
    prepare_analyse_output,
)
from utils.files import write_text
from utils.http import HttpClient
from utils.research_paths import discover_corpus_files, parse_research_filename

logger = logging.getLogger("archivtrace")

Progress = Callable[[str], None]


def run_archivtrace(
    cfg: Config,
    *,
    query: str,
    sites: list[str],
    refresh: bool = False,
    from_scratch: bool = False,
    collecte_seule: bool = False,
    only_matches: bool = True,
    dry_run: bool = False,
    extractor: object | None = None,
    research_dir: Path | None = None,
    on_progress: Progress | None = None,
) -> int:
    """Download and analyse ``query`` on ``sites``.

    A later run reopens the latest notebook and does not search again, unless
    ``refresh`` or ``from_scratch`` is set. Returns 0, or 1 when the language
    model was required and missing.
    """
    output_dir = research_dir or cfg.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    progress = on_progress or (lambda line: print(line, flush=True))
    llm_missing = extractor is None and not collecte_seule and not dry_run
    if llm_missing:
        extractor = _build_extractor(cfg)
        llm_missing = extractor is None
        if llm_missing:
            logger.error("LLM unavailable: collection continues, analysis is postponed.")
            progress("Analysis unavailable")

    lane = AnalysisLane(extractor) if extractor is not None and not collecte_seule and not dry_run else None
    exit_code = 1 if llm_missing else 0
    try:
        for site in sites:
            _run_site(
                cfg,
                query=query,
                site=site,
                output_dir=output_dir,
                refresh=refresh,
                from_scratch=from_scratch,
                collecte_seule=collecte_seule or lane is None,
                only_matches=only_matches,
                dry_run=dry_run,
                lane=lane,
                progress=progress,
            )
    finally:
        if lane is not None:
            lane.close()
    return exit_code


def _build_extractor(cfg: Config) -> object | None:
    from pipeline.llm_gateway import build_llm_gateway
    from pipeline.llm_idea_extractor import LlmIdeaExtractor

    try:
        client = build_llm_gateway(cfg, operation="analyse", task="extraction")
    except ValueError as exc:
        logger.error("%s", exc)
        return None
    if client is None or not client.is_available():
        return None
    return LlmIdeaExtractor(
        client=client,
        max_chars=cfg.llm_max_chars,
        two_pass_extraction=cfg.two_pass_extraction,
    )


def _run_site(
    cfg: Config,
    *,
    query: str,
    site: str,
    output_dir: Path,
    refresh: bool,
    from_scratch: bool,
    collecte_seule: bool,
    only_matches: bool,
    dry_run: bool,
    lane: AnalysisLane | None,
    progress: Progress,
) -> None:
    existing = None if from_scratch else _latest_notebook(output_dir, query, site)
    http = HttpClient(headers=cfg.headers(), timeout=cfg.timeout, delay=cfg.delay)
    if existing is not None and not refresh:
        progress(f"Resume {site}")
        _resume(
            cfg,
            existing=existing,
            http=http,
            lane=lane,
            only_matches=only_matches,
            collecte_seule=collecte_seule,
            dry_run=dry_run,
            progress=progress,
        )
        return

    site_cfg = replace(cfg, dry_run=True) if dry_run else cfg
    connector = build_connector(site, http, site_cfg)
    known_ids: set[str] = set()
    if refresh and existing is not None:
        analyse_path_ready = _analyse_path_for(existing, "pending")
        source_for_ids = analyse_path_ready if analyse_path_ready.exists() else existing
        parsed_ids = read_collection(source_for_ids)
        known_ids = {source.document_id for source in parsed_ids.sources if source.document_id}
        _skip_known(connector, known_ids)
    collector = Collector(
        connector,
        site_cfg,
        reuse_existing=not from_scratch,
    )
    run = collector.open_run(query)
    reporter = MarkdownReporter(max_excerpts=cfg.max_excerpts)
    collecte_path = output_dir / reporter.filename_for(run)
    model = _model_name(lane)
    analyse_path = derive_analyse_output_path(collecte_path, model)
    next_index = 1
    if refresh and existing is not None:
        analyse_path = _analyse_path_for(existing, model)
        if not analyse_path.exists():
            prepare_analyse_output(existing, analyse_path, model=model, force=False)
        parsed = read_collection(analyse_path)
        next_index = len(parsed.sources) + 1
        progress(f"Search {site} (new documents)")
    else:
        progress(f"Search {site}")

    lock = threading.Lock()
    added = 0

    def flush_new_run() -> None:
        text = reporter.render(run, include_llm=True)
        text = annotate_analyse_metadata(text, source_collecte=collecte_path, model=model)
        write_text(analyse_path, text)

    for document in collector.iter_documents(query, run):
        doc_id = document.candidate.document_id
        if doc_id and doc_id in known_ids:
            continue
        title = document.candidate.title or doc_id or "document"
        progress(f"Download {title}")
        if refresh and existing is not None:
            section = reporter._document_section(
                next_index + added,
                document,
                run,
                include_llm=False,
            )
            _append_section(analyse_path, section)
            index = next_index + added
            added += 1
            _submit(document, query, lane, only_matches, progress, lock, analyse_path, index)
        else:
            with lock:
                run.documents.append(document)
                flush_new_run()
            _submit_in_memory(document, query, lane, only_matches, progress, lock, flush_new_run)

    if lane is not None:
        lane.drain()
    if refresh and existing is not None:
        return
    collector._add_observations(run)
    write_text(collecte_path, reporter.render(run, include_llm=False))
    with lock:
        flush_new_run()


def _submit_in_memory(
    document: CollectedDocument,
    query: str,
    lane: AnalysisLane | None,
    only_matches: bool,
    progress: Progress,
    lock: threading.Lock,
    flush: Callable[[], None],
) -> None:
    if not _should_analyse(document, only_matches=only_matches, lane=lane):
        return

    def on_result(extraction: LlmExtraction) -> None:
        with lock:
            document.llm_extraction = extraction
            flush()

    progress(f"Analysis {document.candidate.title}")
    assert lane is not None
    lane.submit(_job(document, query, on_result))


def _submit(
    document: CollectedDocument,
    query: str,
    lane: AnalysisLane | None,
    only_matches: bool,
    progress: Progress,
    lock: threading.Lock,
    analyse_path: Path,
    index: int,
) -> None:
    if not _should_analyse(document, only_matches=only_matches, lane=lane):
        return

    def on_result(extraction: LlmExtraction) -> None:
        with lock:
            text = analyse_path.read_text(encoding="utf-8")
            patched = patch_collection_markdown(text, {index: extraction})
            analyse_path.write_text(patched, encoding="utf-8")

    progress(f"Analysis {document.candidate.title}")
    assert lane is not None
    lane.submit(_job(document, query, on_result))


def _job(
    document: CollectedDocument,
    query: str,
    on_result: Callable[[LlmExtraction], None],
) -> AnalysisJob:
    text = document.extracted or ExtractedText()
    return AnalysisJob(
        query=query,
        title=document.candidate.title or "",
        text=text,
        matches=list(document.matches),
        source=document.candidate.source_url,
        cote=document.candidate.document_id,
        date=str(document.candidate.raw_metadata.get("date") or "") or None,
        on_result=on_result,
    )


def _should_analyse(
    document: CollectedDocument,
    *,
    only_matches: bool,
    lane: AnalysisLane | None,
) -> bool:
    if lane is None or document.extracted is None:
        return False
    if document.extracted.char_count <= 0:
        return False
    if only_matches and document.match_count <= 0:
        return False
    return True


def _resume(
    cfg: Config,
    *,
    existing: Path,
    http: HttpClient,
    lane: AnalysisLane | None,
    only_matches: bool,
    collecte_seule: bool,
    dry_run: bool,
    progress: Progress,
) -> None:
    model = _model_name(lane)
    analyse_path = _analyse_path_for(existing, model)
    if analyse_path != existing and not analyse_path.exists():
        prepare_analyse_output(existing, analyse_path, model=model, force=False)
    parsed = read_collection(analyse_path)
    lock = threading.Lock()
    matcher = KeywordMatcher(
        parsed.query,
        mode=parsed.match_mode,
        context_window=parsed.context_window,
    )
    for source in parsed.sources:
        local = _resolved_local(source)
        if local is None or not _file_ready(local):
            progress(f"Download {source.title}")
            _ensure_local_file(source, http, cfg.download_dir)
            local = _resolved_local(source)
        if collecte_seule or dry_run or lane is None or source.llm_analyzed:
            continue
        if only_matches and source.match_count <= 0:
            continue
        if local is None or not _file_ready(local):
            continue
        extracted = TextExtractor().extract(local)
        if extracted.char_count <= 0:
            continue
        index = source.index

        def on_result(extraction: LlmExtraction, index: int = index) -> None:
            with lock:
                current = analyse_path.read_text(encoding="utf-8")
                analyse_path.write_text(
                    patch_collection_markdown(current, {index: extraction}),
                    encoding="utf-8",
                )

        progress(f"Analysis {source.title}")
        lane.submit(
            AnalysisJob(
                query=parsed.query,
                title=source.title,
                text=extracted,
                matches=matcher.find_in_document(extracted),
                source=source.source_url,
                cote=source.document_id,
                date=source.date,
                on_result=on_result,
            )
        )
    if lane is not None:
        lane.drain()


def _ensure_local_file(source: object, http: HttpClient, download_dir: Path) -> None:
    local = getattr(source, "local_file", None)
    dest: Path | None = None
    if isinstance(local, Path):
        dest = local if local.is_absolute() else Path.cwd() / local
        if _file_ready(dest):
            return
    download_url = getattr(source, "download_url", None)
    if not download_url:
        return
    if dest is None:
        connector = getattr(source, "connector", None) or "wikipedia"
        doc_id = getattr(source, "document_id", None) or "document"
        dest = download_dir / connector / f"{doc_id}.bin"
    if _file_ready(dest):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    http.download(download_url, partial)
    partial.replace(dest)


def _resolved_local(source: object) -> Path | None:
    local = getattr(source, "local_file", None)
    if not isinstance(local, Path):
        return None
    return local if local.is_absolute() else Path.cwd() / local


def _file_ready(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _latest_notebook(output_dir: Path, query: str, site: str) -> Path | None:
    for path in discover_corpus_files(output_dir, query):
        info = parse_research_filename(path)
        if info is not None and info.connector == site:
            return path
    return None


def _analyse_path_for(existing: Path, model: str) -> Path:
    info = parse_research_filename(existing)
    if info is not None and info.is_analyse:
        return existing
    return derive_analyse_output_path(existing, model)


def _model_name(lane: AnalysisLane | None) -> str:
    if lane is None:
        return "none"
    client = getattr(lane._extractor, "client", None)
    model = getattr(client, "model", None)
    return str(model or "llm")


def _skip_known(connector: object, known_ids: set[str]) -> None:
    original = connector.search

    def search(query: str) -> list:
        found = original(query)
        return [item for item in found if item.document_id not in known_ids]

    connector.search = search  # type: ignore[method-assign]


def _append_section(path: Path, section: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    marker = "## Sources ignorées"
    block = section.strip()
    if marker in text:
        text = text.replace(marker, block + "\n\n" + marker, 1)
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")
