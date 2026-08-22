"""Callable pipeline entry points for CLI and future UIs.

CLIs stay thin: parse intention args, resolve Config, then call these helpers.
Policies (OCR, facts mode, NLI/CoVe) live on Config / config.json.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SYNTHESIS_DIR,
    Config,
    resolve_facts_mode,
)
from pipeline.llm_gateway import build_llm_gateway
from pipeline.llm_task_models import get_model_for_task
from pipeline.markdown_reader import merge_collections, read_collection
from pipeline.synthesizer import Synthesizer
from utils.research_paths import discover_corpus_files

logger = logging.getLogger("run_api")


def load_synthesis_collection(
    *,
    query: str | None = None,
    input_path: Path | None = None,
    research_dir: Path | None = None,
) -> Any | None:
    """Load one collecte file or merge multi-site files for query."""
    if query and input_path:
        logger.error("Utiliser --query ou --input, pas les deux.")
        return None
    if not query and not input_path:
        logger.error("Indiquer --query MOTCLE ou --input fichier.md")
        return None

    if input_path is not None:
        if not input_path.exists():
            logger.error("Fichier introuvable: %s", input_path)
            return None
        return read_collection(input_path)

    base = research_dir or DEFAULT_OUTPUT_DIR
    paths = discover_corpus_files(base, query or "")
    if not paths:
        logger.error(
            "Aucun fichier research trouve pour %r dans %s",
            query,
            base,
        )
        return None
    logger.info(
        "Corpus multi-sites (%d fichier(s)):\n  %s",
        len(paths),
        "\n  ".join(str(p) for p in paths),
    )
    collections = [read_collection(p) for p in paths]
    if len(collections) == 1:
        return collections[0]
    return merge_collections(collections)


def run_synthesize(
    cfg: Config,
    *,
    query: str | None = None,
    input_path: Path | None = None,
    research_dir: Path | None = None,
    output_dir: Path | None = None,
    mode: str = "synthese",
    llm_provider: str | None = None,
    allow_single_source_facts: bool = False,
    legacy_corroboration: bool = False,
    facts_mode: str | None = None,
    verify_cove: bool | None = None,
    no_nli: bool = False,
    nli_llm: bool | None = None,
) -> Path | None:
    """Run synthesis using cfg policies; optional CLI overrides for advanced use."""
    collection = load_synthesis_collection(
        query=query, input_path=input_path, research_dir=research_dir
    )
    if collection is None:
        return None

    out_dir = output_dir or DEFAULT_SYNTHESIS_DIR
    task_name = "article_context" if mode == "contexte" else "synthesis"
    task_model = get_model_for_task(task_name, cfg)
    model = task_model.model
    timeout = cfg.ollama_timeout
    num_predict = cfg.synthesis_num_predict
    max_prompt_chars = cfg.synthesis_max_chars
    provider = (llm_provider or cfg.llm_provider or "ollama").strip().lower()

    logger.info(
        "Collecte lue: query=%r, connecteur(s)=%s, %d source(s), "
        "%d extraits, %d analyses LLM",
        collection.query,
        collection.connector,
        len(collection.sources),
        len(collection.sources_with_excerpts),
        len(collection.sources_with_llm_ideas),
    )

    llm = None
    use_template = True
    if provider != "none":
        try:
            client = build_llm_gateway(
                cfg,
                provider=provider,
                operation="synthesize" if mode == "synthese" else "contexte",
                max_tokens=num_predict,
                task=task_name,
            )
        except ValueError as exc:
            logger.error("%s", exc)
            return None
        if client is not None and client.is_available():
            llm = client
            model = client.model
            logger.info(
                "LLM disponible — provider=%s task=%s model=%s thinking=%s timeout=%ds",
                client.provider,
                task_name,
                model,
                client.think,
                int(timeout),
            )
        else:
            logger.warning(
                "LLM indisponible (provider=%s) — repli template",
                provider,
            )

    promotion_mode = resolve_facts_mode(
        cfg,
        facts_mode=facts_mode,
        allow_single_source_facts=allow_single_source_facts,
        legacy_corroboration=legacy_corroboration,
    )
    cove = (
        bool(verify_cove)
        if verify_cove is not None
        else bool(cfg.synthesis_verify_cove)
    )
    nli = False if no_nli else bool(cfg.synthesis_verify_nli)
    nli_use = bool(nli_llm) if nli_llm is not None else bool(cfg.synthesis_nli_llm)

    synthesizer = Synthesizer(
        llm=llm,
        model=model,
        use_template_fallback=use_template,
        mode=mode,
        max_prompt_chars=max_prompt_chars,
        promotion_mode=promotion_mode,
        verify_cove=cove,
        verify_nli=nli,
        nli_use_llm=nli_use,
    )
    result = synthesizer.run(collection)
    path = synthesizer.write(result, out_dir)
    logger.info("%s ecrit: %s (backend=%s)", mode, path, result.llm_backend)

    from pipeline.quality_report import (
        SynthesisTierCounts,
        quality_report_path,
        write_synthesis_quality_report,
    )

    tiers = result.tier_counts or {}
    report_path = quality_report_path(query=collection.query, kind="synthese")
    try:
        write_synthesis_quality_report(
            report_path,
            query=collection.query,
            source_paths=result.source_path,
            tiers=SynthesisTierCounts(
                corroborated=int(tiers.get("corroborated", 0)),
                documented=int(tiers.get("documented", 0)),
                hypotheses=int(tiers.get("hypotheses", 0)),
                grounded_input=int(
                    tiers.get("grounded_input", result.grounded_claim_count)
                ),
                promotion_mode=promotion_mode,
            ),
            llm_backend=result.llm_backend,
            model=result.model,
        )
        logger.info("Rapport qualite: %s", report_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossible d'ecrire le rapport qualite: %s", exc)
    return path


def run_analyse(
    cfg: Config,
    *,
    input_path: Path,
    output_path: Path | None = None,
    in_place: bool = False,
    only_matches: bool = False,
    skip_existing: bool = True,
    force: bool = False,
    llm_provider: str | None = None,
) -> Path | None:
    """Run per-document LLM analysis using cfg policies; return output Markdown path."""
    from pipeline.collection_analyzer import CollectionAnalyzer, load_collection
    from pipeline.llm_gateway import build_llm_gateway
    from pipeline.llm_task_models import get_model_for_task
    from pipeline.llm_validation_stats import VALIDATION_STATS
    from pipeline.quality_report import (
        EXTRACTION_QUALITY,
        quality_report_path,
        write_analyse_quality_report,
    )
    from pipeline.text_extractor import (
        missing_ocr_message,
        missing_pdf_backend_message,
        ocr_available,
        pdf_backend_available,
    )
    from utils.analyse_paths import derive_analyse_output_path, prepare_analyse_output

    task_model = get_model_for_task("extraction", cfg)
    model = task_model.model
    timeout = cfg.ollama_timeout
    max_chars = cfg.llm_max_chars
    num_predict = cfg.ollama_num_predict
    provider = (llm_provider or cfg.llm_provider or "ollama").strip().lower()

    try:
        client = build_llm_gateway(
            cfg,
            provider=provider,
            operation="analyse",
            max_tokens=num_predict,
            task="extraction",
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return None
    if client is None:
        logger.error("llm_provider=none : l'analyse documentaire nécessite un LLM.")
        return None

    model = client.model
    logger.info(
        "LLM: provider=%s task=extraction model=%s thinking=%s "
        "timeout=%ds max_chars=%d max_tokens=%d",
        client.provider,
        model,
        client.think,
        int(timeout),
        max_chars,
        num_predict,
    )
    if not client.is_available():
        logger.error(
            "LLM indisponible (provider=%s model=%s) — vérifier le service / la clé API",
            client.provider,
            model,
        )
        return None

    if not pdf_backend_available():
        logger.error(missing_pdf_backend_message())
        return None

    if (cfg.enable_ocr or cfg.auto_ocr) and not ocr_available():
        logger.error(missing_ocr_message())
        return None
    if cfg.enable_ocr:
        logger.info("OCR activé (lang=%s)", cfg.ocr_lang)
    elif cfg.auto_ocr:
        logger.info("Auto-OCR activé (lang=%s)", cfg.ocr_lang)
    if cfg.two_pass_extraction:
        logger.info("Two-pass extraction activé (passe descriptive si besoin)")

    in_place = in_place
    if in_place:
        output_path = output_path or input_path
    else:
        output_path = output_path or derive_analyse_output_path(input_path, model)

    work_path = prepare_analyse_output(
        input_path, output_path, model=model, force=force and not in_place
    )
    if work_path != input_path:
        logger.info("Collecte source: %s", input_path)
        logger.info("Fichier analyse: %s", work_path)

    collection = load_collection(work_path)
    pending = sum(1 for s in collection.sources if s.llm_status == "pending")
    failed = sum(1 for s in collection.sources if s.llm_status == "failed")
    done = sum(1 for s in collection.sources if s.llm_analyzed)
    logger.info(
        "État LLM: %d terminée(s), %d échec(s) à réessayer, %d en attente",
        done,
        failed,
        pending,
    )
    already_done = done
    logger.info(
        "Collecte lue: query=%r, %d source(s), %d déjà analysée(s)",
        collection.query,
        len(collection.sources),
        already_done,
    )

    analyzer = CollectionAnalyzer(
        client=client,
        download_dir=cfg.download_dir,
        max_chars=max_chars,
        enable_ocr=cfg.enable_ocr,
        auto_ocr=cfg.auto_ocr,
        two_pass_extraction=cfg.two_pass_extraction,
        ocr_lang=cfg.ocr_lang,
    )
    EXTRACTION_QUALITY.reset()
    VALIDATION_STATS.reset()
    patched, stats = analyzer.run(
        collection,
        only_matches=only_matches,
        skip_existing=skip_existing,
        force=force,
        output_path=work_path,
    )

    analyzer.write(patched, work_path)
    logger.info(
        "Markdown enrichi: %s (%d analysée(s), %d ignorée(s), %d échec(s))",
        work_path,
        stats.sources_analyzed,
        stats.sources_skipped,
        stats.sources_failed,
    )
    for message in stats.messages:
        logger.info("  %s", message)
    for model_id, vstats in VALIDATION_STATS.snapshot().items():
        logger.info(
            "Validation JSON modèle=%s: ok=%s fail=%s rate=%.1f%%",
            model_id,
            vstats["ok"],
            vstats["fail"],
            100.0 * float(vstats["failure_rate"]),
        )
    report_path = quality_report_path(query=collection.query, kind="analyse")
    try:
        write_analyse_quality_report(
            report_path,
            analyse_path=work_path,
        )
        logger.info("Rapport qualité: %s", report_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossible d'écrire le rapport qualité: %s", exc)
    if stats.sources_failed and not stats.sources_analyzed:
        return None
    return work_path

