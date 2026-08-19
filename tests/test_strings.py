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
