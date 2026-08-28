from __future__ import annotations

import pytest

from brain.features import (
    DEFAULT_BASE_FEATURE_SET,
    FEATURE_COLUMNS_TECHNICAL_V2,
    FEATURE_SET_OVERLAYS_BY_ASSET_CLASS,
    compose_feature_set,
    feature_columns_for_set,
    feature_set_for_asset_class,
)


def test_feature_columns_for_set_technical_v2_is_behavior_identical():
    """spec: 'technical_v2 remains behavior-identical' -- no asset_class kwarg
    at all reproduces the exact pre-change column list."""
    assert feature_columns_for_set("technical_v2") == FEATURE_COLUMNS_TECHNICAL_V2


@pytest.mark.parametrize("asset_class", ["crypto", "unknown_class", None])
def test_feature_columns_for_set_falls_back_cleanly_without_overlay(asset_class):
    """spec: 'Asset class without an overlay falls back cleanly' -- with an
    empty FEATURE_SET_OVERLAYS_BY_ASSET_CLASS, every asset_class (including
    None) resolves to the same technical_v2 spine, never raising."""
    assert feature_columns_for_set("technical_v2", asset_class=asset_class) == FEATURE_COLUMNS_TECHNICAL_V2


def test_feature_columns_for_set_unknown_name_raises_regardless_of_asset_class():
    with pytest.raises(ValueError, match="Unknown feature_set"):
        feature_columns_for_set("does_not_exist")

    with pytest.raises(ValueError, match="Unknown feature_set"):
        feature_columns_for_set("does_not_exist", asset_class="crypto")


def test_feature_set_for_asset_class_never_raises_and_falls_back_to_base():
    assert feature_set_for_asset_class("crypto") == DEFAULT_BASE_FEATURE_SET
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
