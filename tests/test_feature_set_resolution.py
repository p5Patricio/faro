from __future__ import annotations

import pytest

from brain import fundamental_factors, sentiment_factors, technical_factors_v2
from brain.features import (
    DEFAULT_BASE_FEATURE_SET,
    FEATURE_COLUMNS_TECHNICAL_V2,
    FEATURE_SET_OVERLAYS_BY_ASSET_CLASS,
    FUNDAMENTAL_OVERLAY_COLUMNS,
    SENTIMENT_OVERLAY_COLUMNS,
    TECHNICAL_ALPHA_OVERLAY_COLUMNS,
    compose_feature_set,
    feature_columns_for_set,
    feature_set_for_asset_class,
)


def test_feature_columns_for_set_technical_v2_is_behavior_identical():
    """spec: 'technical_v2 remains behavior-identical' -- no asset_class kwarg
    at all reproduces the exact pre-change column list."""
    assert feature_columns_for_set("technical_v2") == FEATURE_COLUMNS_TECHNICAL_V2


@pytest.mark.parametrize("asset_class", ["unknown_class", "forex", None])
def test_feature_columns_for_set_falls_back_cleanly_without_overlay(asset_class):
    """spec: 'Asset class without an overlay falls back cleanly' -- for any
    asset_class NOT registered in FEATURE_SET_OVERLAYS_BY_ASSET_CLASS
    (including None), resolution falls back to the same technical_v2 spine,
    never raising. "crypto" is excluded here since the crypto overlay
    (technical_alpha_v1) is registered for real -- see
    tests/test_crypto_feature_set.py."""
    assert feature_columns_for_set("technical_v2", asset_class=asset_class) == FEATURE_COLUMNS_TECHNICAL_V2


def test_feature_columns_for_set_unknown_name_raises_regardless_of_asset_class():
    """"crypto" is deliberately not used as the second case here -- it now
    has a REGISTERED overlay (technical_alpha_v1), which wins over an
    explicit (even invalid) feature_set argument by design; see
    test_feature_columns_for_set_registered_overlay_wins_over_invalid_explicit_feature_set
    in tests/test_crypto_feature_set.py. An unregistered asset_class must
    still not rescue a bad feature_set name."""
    with pytest.raises(ValueError, match="Unknown feature_set"):
        feature_columns_for_set("does_not_exist")

    with pytest.raises(ValueError, match="Unknown feature_set"):
        feature_columns_for_set("does_not_exist", asset_class="unknown_class")


def test_feature_set_for_asset_class_never_raises_and_falls_back_to_base():
    """"crypto" is deliberately not used here -- it now resolves to a
    registered overlay (technical_alpha_v1), not the base feature set; see
    tests/test_crypto_feature_set.py."""
    assert feature_set_for_asset_class("unknown_class") == DEFAULT_BASE_FEATURE_SET
    assert feature_set_for_asset_class("") == DEFAULT_BASE_FEATURE_SET
    assert feature_set_for_asset_class(None) == DEFAULT_BASE_FEATURE_SET


def test_feature_set_for_asset_class_resolves_registered_overlay(monkeypatch):
    """spec: 'Asset class with a registered overlay resolves the composed set' --
    proven here via monkeypatch since this change ships the registry empty;
    sibling changes populate it for real."""
    monkeypatch.setitem(FEATURE_SET_OVERLAYS_BY_ASSET_CLASS, "crypto", "crypto_v1")
    assert feature_set_for_asset_class("crypto") == "crypto_v1"
    assert feature_set_for_asset_class("CRYPTO") == "crypto_v1"
    assert feature_set_for_asset_class("  crypto  ") == "crypto_v1"


def test_feature_columns_for_set_resolves_via_registered_overlay(monkeypatch):
    monkeypatch.setitem(FEATURE_SET_OVERLAYS_BY_ASSET_CLASS, "crypto", "technical_v1")
    assert feature_columns_for_set("technical_v2", asset_class="crypto") == feature_columns_for_set("technical_v1")


def test_compose_feature_set_appends_overlay_columns_without_mutating_spine():
    composed = compose_feature_set("technical_v2", ["funding_rate_z"])
    assert composed == [*FEATURE_COLUMNS_TECHNICAL_V2, "funding_rate_z"]
    # technical_v2 itself is never mutated
    assert feature_columns_for_set("technical_v2") == FEATURE_COLUMNS_TECHNICAL_V2


# -- fundamental-analysis (Phase 4): C1-d / C2 regression -------------------


def test_technical_v2_columns_byte_identical():
    """C1-d / C2: registering fundamental_v1 must not perturb technical_v2's
    resolution at all -- every promoted technical_v2 model stays untouched."""
    assert feature_columns_for_set("technical_v2") == FEATURE_COLUMNS_TECHNICAL_V2


def test_fundamental_v1_composes_technical_v2_plus_three_factors():
    """spec: 'fundamental_v1 composes the spine plus three factors;
    technical_v2 is untouched' -- fundamental_v1 is technical_v2's column
    list followed by exactly the three composite factor columns, no
    NULL-padding, no raw ratios (ROA, current ratio, leverage, gross margin,
    asset turnover) ever exposed as columns."""
    technical_columns = feature_columns_for_set("technical_v2")
    fundamental_columns = feature_columns_for_set("fundamental_v1")

    assert fundamental_columns[:25] == technical_columns
    assert len(fundamental_columns) == 28
    assert fundamental_columns[25:] == ["piotroski_f_score", "altman_z_score", "gross_profitability"]

    # Kept in sync by this contract test, not by a shared import --
    # brain/features.py intentionally never imports brain/fundamental_factors.py.
    assert set(FUNDAMENTAL_OVERLAY_COLUMNS) == set(fundamental_factors.FACTOR_KEYS)


def test_technical_alpha_v1_composes_technical_v2_plus_nineteen_factors():
    """spec: 'technical_alpha_v1 composes the spine plus the technical-alpha
    factors; technical_v2 is untouched' -- technical_alpha_v1 is technical_v2's
    column list followed by exactly the 19 technical-alpha factor columns."""
    technical_columns = feature_columns_for_set("technical_v2")
    technical_alpha_columns = feature_columns_for_set("technical_alpha_v1")

    assert technical_alpha_columns[:25] == technical_columns
    assert len(technical_alpha_columns) == 44
    assert technical_alpha_columns[25:] == TECHNICAL_ALPHA_OVERLAY_COLUMNS

    # Kept in sync by this contract test, not by a shared import --
    # brain/features.py intentionally never imports brain/technical_factors_v2.py.
    assert set(TECHNICAL_ALPHA_OVERLAY_COLUMNS) == set(technical_factors_v2.FACTOR_KEYS)


def test_sentiment_v1_composes_technical_v2_plus_two_factors():
    """spec: 'sentiment_v1 composes the spine plus the sentiment factors;
    technical_v2 is untouched' -- sentiment_v1 is technical_v2's column list
    followed by exactly the two sentiment factor columns. Unlike
    technical_alpha_v1, sentiment_v1 is composed onto technical_v2 directly
    (not technical_alpha_v1), same base fundamental_v1 uses -- see
    brain/materialize_sentiment.py's module docstring for why."""
    technical_columns = feature_columns_for_set("technical_v2")
    sentiment_columns = feature_columns_for_set("sentiment_v1")

    assert sentiment_columns[:25] == technical_columns
    assert len(sentiment_columns) == 27
    assert sentiment_columns[25:] == SENTIMENT_OVERLAY_COLUMNS

    # Kept in sync by this contract test, not by a shared import --
    # brain/features.py intentionally never imports brain/sentiment_factors.py.
    assert set(SENTIMENT_OVERLAY_COLUMNS) == set(sentiment_factors.FACTOR_KEYS)
