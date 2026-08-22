"""Tests for string utilities used in slugs, normalization and variants."""

from __future__ import annotations

from utils.strings import keyword_variants, normalize, slugify, strip_accents


def test_strip_accents():
    assert strip_accents("Rochécardon") == "Rochecardon"


def test_normalize_lowercases_and_strips_accents():
    assert normalize("  La  Vallée  ") == "la vallee"


def test_slugify_for_filenames():
    assert slugify("Rue de Rochecardon!") == "rue-de-rochecardon"


def test_keyword_variants_are_unique_and_ordered():
    variants = keyword_variants("Rochecardon")
    assert variants[0] == "Rochecardon"
    assert len(variants) == len(set(variants))
    assert "rochecardon" in variants


def test_keyword_variants_include_hyphen_and_space_forms():
    variants = keyword_variants("Rochecardon")
    lowered = {v.casefold() for v in variants}
    assert "roche-cardon" in lowered
    assert "roche cardon" in lowered
    assert "rochecardon" in lowered


def test_keyword_variants_from_hyphenated_query():
    variants = keyword_variants("Roche-Cardon")
    lowered = {v.casefold() for v in variants}
    assert "roche-cardon" in lowered
    assert "roche cardon" in lowered
    assert "rochecardon" in lowered


def test_keyword_variants_accented_toponym():
    variants = keyword_variants("Rochécardon")
    lowered = {strip_accents(v).casefold() for v in variants}
    assert "rochecardon" in lowered
    assert "roche-cardon" in lowered
