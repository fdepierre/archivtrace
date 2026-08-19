"""Tests for analyse resume / filter policy."""

from __future__ import annotations

from pipeline.analyse_policy import should_process
from pipeline.markdown_format import (
    STATUS_FAILED,
    STATUS_IGNORED,
    STATUS_PENDING,
    STATUS_SUCCESS,
)
from pipeline.markdown_reader import ParsedSource


def _src(*, status: str, matches: int = 1, analyzed: bool = False) -> ParsedSource:
    return ParsedSource(
        index=1,
        title="Doc",
        match_count=matches,
        llm_status=status,
        llm_analyzed=analyzed,
    )


def test_skip_success_when_skip_existing():
    d = should_process(
        _src(status=STATUS_SUCCESS, analyzed=True),
        skip_existing=True,
        only_matches=False,
        enable_ocr=False,
    )
    assert not d.process
    assert "déjà" in (d.reason or "")


def test_retry_ignored_when_ocr_enabled():
    d = should_process(
        _src(status=STATUS_IGNORED, analyzed=True),
        skip_existing=True,
        only_matches=False,
        enable_ocr=True,
    )
    assert d.process


def test_skip_ignored_without_ocr():
    d = should_process(
        _src(status=STATUS_IGNORED, analyzed=True),
        skip_existing=True,
        only_matches=False,
        enable_ocr=False,
    )
    assert not d.process


def test_only_matches_skips_zero():
    d = should_process(
        _src(status=STATUS_PENDING, matches=0),
        skip_existing=True,
        only_matches=True,
        enable_ocr=False,
    )
    assert not d.process
    assert "match" in (d.reason or "")


def test_failed_is_retried():
    d = should_process(
        _src(status=STATUS_FAILED, analyzed=False),
        skip_existing=True,
        only_matches=False,
        enable_ocr=False,
    )
    assert d.process
