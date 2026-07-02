"""
Tests for vcf_color_service.core.ColorMapper.
"""

import json
from pathlib import Path

import pytest

from vcf_color_service import ColorMapper

_HERE = Path(__file__).resolve().parent
_CONFIG = _HERE.parent / "config.json"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture(scope="session")
def mapper() -> ColorMapper:
    assert _CONFIG.exists(), f"config.json not found at {_CONFIG}"
    return ColorMapper.load(_CONFIG)


# ------------------------------------------------------------------
# Basic lookup tests
# ------------------------------------------------------------------

class TestBasicLookups:
    def test_aci_to_rgb_known(self, mapper):
        assert mapper.aci_to_rgb(0) == (0, 0, 0)
        assert mapper.aci_to_rgb(1) == (255, 0, 0)
        assert mapper.aci_to_rgb(7) == (0, 0, 0)
        assert mapper.aci_to_rgb(52) == (0, 204, 204)

    def test_aci_to_rgb_unknown(self, mapper):
        assert mapper.aci_to_rgb(999) == (0, 0, 0)

    def test_aci_to_name_cs(self, mapper):
        assert mapper.aci_to_name(0, "cs") == "ByBlock"
        assert mapper.aci_to_name(7, "cs") == "Černá"
        assert mapper.aci_to_name(52, "cs") == "Tyrkysová"

    def test_aci_to_name_en(self, mapper):
        assert mapper.aci_to_name(1, "en") == "Red"
        assert mapper.aci_to_name(2, "en") == "Yellow"
        assert mapper.aci_to_name(52, "en") == "Teal"

    def test_aci_to_name_unknown(self, mapper):
        assert mapper.aci_to_name(999) == "ACI_999"

    def test_aci_to_vcf_params(self, mapper):
        params = mapper.aci_to_vcf_params(7)
        assert params["cutter_type"] == "Vibrate cutter"
        assert params["speed_mms"] == 80
        assert params["h1_mm"] == 24.0

    def test_aci_to_vcf_params_vslot(self, mapper):
        params = mapper.aci_to_vcf_params(3)
        assert params["cutter_type"] == "V-slot"
        assert params["direction"] == "Cut both side"

    def test_aci_to_cutter_id(self, mapper):
        assert mapper.aci_to_cutter_id(7) == 1  # Vibrate cutter
        assert mapper.aci_to_cutter_id(3) == 4  # V-slot

    def test_aci_to_direction_id(self, mapper):
        assert mapper.aci_to_direction_id(7) == 0   # N/A
        assert mapper.aci_to_direction_id(2) == 1   # Left


# ------------------------------------------------------------------
# Reverse lookup tests
# ------------------------------------------------------------------

class TestReverseLookups:
    def test_rgb_to_aci_exact(self, mapper):
        assert mapper.rgb_to_aci(0, 0, 0) == 0   # multiple matches, nearest wins
        assert mapper.rgb_to_aci(255, 0, 0) == 1

    def test_rgb_to_aci_teal(self, mapper):
        assert mapper.rgb_to_aci(0, 204, 204) == 52

    def test_hex_to_aci(self, mapper):
        assert mapper.hex_to_aci("00ff00") == 3
        assert mapper.hex_to_aci("00cccc") == 52
        assert mapper.hex_to_aci("ff0000") == 1


# ------------------------------------------------------------------
# Export tests — compare with original hardcoded dicts
# ------------------------------------------------------------------

class TestExports:
    def test_export_color_map_contains_black(self, mapper):
        cm = mapper.export_color_map()
        assert "000000" in cm
        assert cm["000000"] == "Černá" or cm["000000"] == "ByBlock"

    def test_export_color_map_teal(self, mapper):
        cm = mapper.export_color_map()
        assert "00cccc" in cm
        assert "00cccc" not in cm or "Tyrkysová" in cm.values()

    def test_export_aci_names(self, mapper):
        names = mapper.export_aci_names()
        assert names[1] == "Red"
        assert names[7] == "Black"
        assert names[52] == "Teal"

    def test_export_aci_to_rgb(self, mapper):
        rgb = mapper.export_aci_to_rgb()
        assert rgb[1] == (255, 0, 0)
        assert rgb[52] == (0, 204, 204)

    def test_export_dxf_config_structure(self, mapper):
        cfg = mapper.export_dxf_config()
        assert "aci_color_mapping" in cfg
        assert "default_feed_rate_mm_per_sec" in cfg
        aci7 = cfg["aci_color_mapping"]["7"]
        assert aci7["cutter_type"] == "Vibrate cutter"
        assert aci7["validation_status"] == "native_vcf"

    def test_export_vcf_config_structure(self, mapper):
        cfg = mapper.export_vcf_config()
        assert "aci_color_mapping" in cfg
        assert "defaults" in cfg


# ------------------------------------------------------------------
# Validation tests
# ------------------------------------------------------------------

class TestValidation:
    def test_validate_no_critical_errors(self, mapper):
        warnings = mapper.validate()
        for w in warnings:
            assert "missing" not in w, f"Critical: {w}"

    def test_validate_returns_list(self, mapper):
        warnings = mapper.validate()
        assert isinstance(warnings, list)


# ------------------------------------------------------------------
# Roundtrip consistency tests
# ------------------------------------------------------------------

class TestRoundtrip:
    def test_rgb_to_aci_to_rgb_unique(self, mapper):
        """Test roundtrip for colors with unique RGB (skip ACI 0/7 conflict)."""
        for aci_str in mapper._colors:
            aci = int(aci_str)
            r, g, b = mapper.aci_to_rgb(aci)
            # ACI 0 and 7 share RGB(0,0,0) — skip
            if (r, g, b) == (0, 0, 0):
                continue
            back = mapper.rgb_to_aci(r, g, b)
            assert back == aci, f"Roundtrip failed for ACI {aci}: got {back}"

    def test_export_import_consistency(self, mapper):
        rgb_dict = mapper.export_aci_to_rgb()
        for aci, (r, g, b) in rgb_dict.items():
            assert mapper.aci_to_rgb(aci) == (r, g, b)


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_mapper(self):
        empty = ColorMapper({"colors": {}, "cutter_types": {}, "directions": {}})
        assert empty.aci_to_rgb(7) == (0, 0, 0)
        assert empty.aci_to_name(7) == "ACI_7"
        assert empty.aci_to_vcf_params(7) == {}

    def test_load_nonexistent_path(self):
        mapper = ColorMapper.load("/nonexistent/path.json")
        assert mapper.aci_to_rgb(7) == (0, 0, 0)