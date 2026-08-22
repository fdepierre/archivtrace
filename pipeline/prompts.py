"""LLM prompts — thin re-exports over versioned files in ``prompts/``.

Edit wording in ``prompts/*.vN.xml.txt``, not here. Bump the version number
in the filename and header when changing behaviour for regression tests.
"""

from __future__ import annotations

from pipeline.prompt_loader import load_prompt

_ANALYZE = load_prompt("analyze_document")
_ANALYZE_DESC = load_prompt("analyze_document_descriptive")
_SYNTHESIS = load_prompt("synthesize_claims")
_ARTICLE = load_prompt("article_context")
_CLASSIFY = load_prompt("classify_source")

# Backward-compatible system-prompt constants (tests / older imports).
IDEA_EXTRACTION_SYSTEM = _ANALYZE.system
SYNTHESIS_SYSTEM = _SYNTHESIS.system
ARTICLE_CONTEXT_SYSTEM = _ARTICLE.system
CLASSIFY_SOURCE_SYSTEM = _CLASSIFY.system

ANALYZE_DOCUMENT_PROMPT = _ANALYZE
ANALYZE_DOCUMENT_DESCRIPTIVE_PROMPT = _ANALYZE_DESC
SYNTHESIZE_CLAIMS_PROMPT = _SYNTHESIS
ARTICLE_CONTEXT_PROMPT = _ARTICLE
CLASSIFY_SOURCE_PROMPT = _CLASSIFY

PROMPT_VERSIONS = {
    _ANALYZE.id: _ANALYZE.version,
    _ANALYZE_DESC.id: _ANALYZE_DESC.version,
    _SYNTHESIS.id: _SYNTHESIS.version,
    _ARTICLE.id: _ARTICLE.version,
    _CLASSIFY.id: _CLASSIFY.version,
}
