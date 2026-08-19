"""Patch LLM analysis sections into an existing collection Markdown file."""



from __future__ import annotations



import re



from models import LlmExtraction

from pipeline.markdown_format import (

    EXCERPTS_HEADING,

    LLM_HEADING,

    LLM_COUNT_RE,

    NEXT_SUBSECTION_RE,

    SOURCE_INDEX_RE,

    SOURCE_SPLIT_RE,

    SUMMARY_HEADING,

    format_llm_section,

    llm_count_line,

)



# Re-export for callers that imported from this module.

__all__ = ["format_llm_section", "patch_collection_markdown"]





def patch_collection_markdown(

    text: str,

    updates: dict[int, LlmExtraction],

    *,

    llm_count: int | None = None,

) -> str:

    """Insert or replace LLM sections for source indices (1-based)."""

    parts = SOURCE_SPLIT_RE.split(text)

    if len(parts) <= 1:

        return text



    head = parts[0]

    source_parts = parts[1:]

    patched_sources: list[str] = []

    for part in source_parts:

        index_match = SOURCE_INDEX_RE.search(part)

        if not index_match:

            patched_sources.append(part)

            continue

        index = int(index_match.group(1))

        if index in updates:

            part = _patch_source_part(part, updates[index])

        patched_sources.append(part)



    body = head + "".join(patched_sources)

    if llm_count is not None:

        body = _update_summary_llm_count(body, llm_count)

    return body





def _patch_source_part(part: str, extraction: LlmExtraction) -> str:

    block = format_llm_section(extraction)

    if LLM_HEADING in part:

        pattern = re.compile(

            rf"^{re.escape(LLM_HEADING)}.*?(?=^{re.escape('### ')}|\Z)",

            re.MULTILINE | re.DOTALL,

        )

        return pattern.sub(lambda _m: block + "\n\n", part, count=1)



    pos = part.find(EXCERPTS_HEADING)

    if pos == -1:

        return part.rstrip() + "\n\n" + block + "\n\n"



    after_heading = pos + len(EXCERPTS_HEADING)

    rest = part[after_heading:]

    next_match = NEXT_SUBSECTION_RE.search(rest)

    insert_at = after_heading + (next_match.start() if next_match else len(rest))

    return part[:insert_at].rstrip() + "\n\n" + block + "\n\n" + part[insert_at:].lstrip()





def _update_summary_llm_count(text: str, count: int) -> str:

    replacement = llm_count_line(count)

    if LLM_COUNT_RE.search(text):

        return LLM_COUNT_RE.sub(replacement, text, count=1)

    summary_anchor = SUMMARY_HEADING + "\n"

    if summary_anchor not in text:

        return text

    return text.replace(summary_anchor, summary_anchor + replacement + "\n", 1)


