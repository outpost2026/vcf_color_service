"""
Core module — ColorMapper class.

Provides bidirectional ACI ↔ RGB ↔ name ↔ VCF params lookup
with no external dependencies (stdlib only).
"""

from __future__ import annotations

import json
import math
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# ColorMapper
# ---------------------------------------------------------------------------

class ColorMapper:
    """Single source of truth for ACI color mapping across all repos.

    Usage:
        mapper = ColorMapper.load()
        rgb = mapper.aci_to_rgb(7)          # → (0, 0, 0)
        name = mapper.aci_to_name(52, "cs") # → "Tyrkysová"
        params = mapper.aci_to_vcf_params(3) # → dict with speed, cutter, ...
        aci = mapper.rgb_to_aci(0, 0, 0)   # → 7  (nearest Euclidean)
    """

    def __init__(self, data: dict[str, Any]):
        self._colors: dict[str, dict] = data.get("colors", {})
        self._cutter_types: dict[str, dict] = data.get("cutter_types", {})
        self._directions: dict[str, dict] = data.get("directions", {})
        self._meta = {k: v for k, v in data.items() if k.startswith("_")}

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None = None) -> ColorMapper:
        """Load config from JSON file. Defaults to config.json next to this module."""
        if path is None:
            path = _CONFIG_DIR / "config.json"
        p = Path(path)
        if not p.exists():
            logger.warning("%s not found — using empty mapper", p)
            return cls({"colors": {}, "cutter_types": {}, "directions": {}})
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    # ------------------------------------------------------------------
    # Lookups — ACI → value
    # ------------------------------------------------------------------

    def aci_to_rgb(self, aci: int) -> tuple[int, int, int]:
        """ACI → (R, G, B). Returns (0,0,0) if unknown."""
        entry = self._colors.get(str(aci))
        if entry is None:
            logger.warning("Unknown ACI %d — fallback black", aci)
            return (0, 0, 0)
        rgb = entry.get("rgb", [0, 0, 0])
        return (rgb[0], rgb[1], rgb[2])

    def aci_to_name(self, aci: int, lang: str = "cs") -> str:
        """ACI → human-readable name in given language."""
        entry = self._colors.get(str(aci))
        if entry is None:
            return f"ACI_{aci}"
        key = "name_cs" if lang == "cs" else "name_en"
        return entry.get(key, f"ACI_{aci}")

    def aci_to_vcf_params(self, aci: int) -> dict:
        """ACI → VCF layer parameters dict (copy, safe to mutate)."""
        entry = self._colors.get(str(aci))
        if entry is None:
            return {}
        params = entry.get("vcf_params", {})
        return dict(params)

    def aci_to_cutter_id(self, aci: int) -> int:
        """ACI → numeric cutter type ID (1-5)."""
        params = self.aci_to_vcf_params(aci)
        cutter_name = params.get("cutter_type", "Vibrate cutter")
        return self._cutter_types.get(cutter_name, {}).get("id", 1)

    def aci_to_direction_id(self, aci: int) -> int:
        """ACI → numeric direction ID (0-3)."""
        params = self.aci_to_vcf_params(aci)
        dir_name = params.get("direction", "N/A")
        return self._directions.get(dir_name, {}).get("id", 0)

    def aci_validation_status(self, aci: int) -> str:
        """ACI → validation status string."""
        entry = self._colors.get(str(aci))
        if entry is None:
            return "unknown"
        return entry.get("validation_status", "unknown")

    # ------------------------------------------------------------------
    # Lookups — reverse (RGB → ACI)
    # ------------------------------------------------------------------

    def rgb_to_aci(self, r: int, g: int, b: int, epsilon: int = 5) -> int:
        """RGB → nearest ACI by Euclidean distance.

        If exact match exists within `epsilon`, returns it.
        Otherwise returns nearest neighbor by Euclidean distance.
        """
        best_aci = 7
        best_dist = float("inf")
        for aci_str, entry in self._colors.items():
            cr, cg, cb = entry.get("rgb", [0, 0, 0])
            dr, dg, db = r - cr, g - cg, b - cb
            dist = dr * dr + dg * dg + db * db
            if dist == 0:
                return int(aci_str)
            if dist < best_dist:
                best_dist = dist
                best_aci = int(aci_str)
        return best_aci

    def hex_to_aci(self, hex_rgb: str) -> int:
        """Hex RGB string (e.g. '00cccc', '0x00cccc') → nearest ACI."""
        val = hex_rgb.lower().replace("0x", "").replace("#", "").strip()
        val = val.zfill(6)
        r = int(val[0:2], 16)
        g = int(val[2:4], 16)
        b = int(val[4:6], 16)
        return self.rgb_to_aci(r, g, b)

    # ------------------------------------------------------------------
    # Export helpers — for backward compatibility with each repo
    # ------------------------------------------------------------------

    def export_color_map(self) -> dict[str, str]:
        """Export hex→name dict for vcf_parser_b2b.COLOR_MAP.

        Example: {"000000": "Černá", "00ff00": "Zelená", ...}
        """
        result = {}
        for aci_str, entry in self._colors.items():
            rgb = entry.get("rgb", [0, 0, 0])
            hex_key = f"{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            name = entry.get("name_cs", f"ACI_{aci_str}")
            result[hex_key] = name
        return result

    def export_aci_names(self) -> dict[int, str]:
        """Export ACI→English name dict for dxf_integrace._ACI_COLOR_NAMES.

        Example: {1: "Red", 7: "Black", ...}
        """
        return {
            int(aci_str): entry.get("name_en", f"ACI_{aci_str}")
            for aci_str, entry in self._colors.items()
        }

    def export_aci_to_rgb(self) -> dict[int, tuple[int, int, int]]:
        """Export ACI→RGB dict for Vcf-compiler.ACI_TO_RGB.

        Example: {1: (255, 0, 0), 7: (0, 0, 0), ...}
        """
        return {
            int(aci_str): (entry["rgb"][0], entry["rgb"][1], entry["rgb"][2])
            for aci_str, entry in self._colors.items()
        }

    def export_dxf_config(self) -> dict:
        """Export dxf_tool_config.json style dict.

        Returns {"aci_color_mapping": {...}, "default_feed_rate_mm_per_sec": 200}
        """
        mapping = {}
        for aci_str, entry in self._colors.items():
            params = entry.get("vcf_params", {})
            mapping[aci_str] = {
                "cutter_type": params.get("cutter_type", "Vibrate cutter"),
                "base_speed_mms": params.get("speed_mms", 200),
                "direction": params.get("direction", "N/A"),
                "h2_mm": params.get("h2_mm", -0.3),
                "vs_comp_mm": params.get("vs_comp_mm", 0.0),
                "start_extension_mm": params.get("start_extension_mm", 0.0),
                "end_extension_mm": params.get("end_extension_mm", 0.0),
                "is_output": params.get("is_output", True),
                "validation_status": entry.get("validation_status", "hypothesis"),
            }
        return {
            "aci_color_mapping": mapping,
            "default_feed_rate_mm_per_sec": 200,
        }

    def export_vcf_config(self) -> dict:
        """Export vcf_compiler_map_config.json style dict.

        Returns {"aci_color_mapping": {...}, "defaults": {...}}
        """
        mapping = {}
        for aci_str, entry in self._colors.items():
            params = entry.get("vcf_params", {})
            mapping[aci_str] = {
                "cutter_type": params.get("cutter_type", "Vibrate cutter"),
                "speed_mms": params.get("speed_mms", 200),
                "direction": params.get("direction", "N/A"),
                "h1_mm": params.get("h1_mm", 2.0),
                "h2_mm": params.get("h2_mm", -0.3),
                "vs_comp_mm": params.get("vs_comp_mm", 0.0),
                "start_extension_mm": params.get("start_extension_mm", 0.0),
                "end_extension_mm": params.get("end_extension_mm", 0.0),
                "is_output": params.get("is_output", True),
                "number_of_feeding": params.get("number_of_feeding", 1),
            }
        return {
            "aci_color_mapping": mapping,
            "defaults": {
                "h1_mm": 24.0,
                "number_of_feeding": 1,
                "fallback_cutter_type": "Vibrate cutter",
                "fallback_speed_mms": 200.0,
                "fallback_direction": "N/A",
                "fallback_h2_mm": -0.3,
                "fallback_start_extension_mm": 0.0,
                "fallback_end_extension_mm": 0.0,
                "fallback_is_output": True,
            },
        }

    def export_viz_colors(self) -> dict[int, str]:
        """Export ACI→hex color string for dxf_integrace._VIZ_COLORS.

        Example: {1: "#FF0000", 7: "#000000", ...}
        """
        return {
            int(aci_str): f"#{entry['rgb'][0]:02X}{entry['rgb'][1]:02X}{entry['rgb'][2]:02X}"
            for aci_str, entry in self._colors.items()
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Run integrity checks. Returns list of warning strings (empty = all OK)."""
        warnings: list[str] = []
        seen_rgb: set[tuple[int, int, int]] = set()
        for aci_str, entry in self._colors.items():
            aci = int(aci_str)
            rgb = tuple(entry.get("rgb", []))
            if len(rgb) != 3:
                warnings.append(f"ACI {aci}: invalid RGB {rgb}")
                continue
            if rgb in seen_rgb:
                warnings.append(f"ACI {aci}: duplicate RGB {rgb}")
            seen_rgb.add(rgb)

            vcf = entry.get("vcf_params", {})
            required = ["cutter_type", "speed_mms", "direction", "h1_mm", "h2_mm", "is_output"]
            for field in required:
                if field not in vcf:
                    warnings.append(f"ACI {aci}: missing vcf_params.{field}")

            status = entry.get("validation_status", "")
            valid_statuses = {"native_vcf", "calibrated", "hypothesis", "conflict_need_resolution"}
            if status not in valid_statuses:
                warnings.append(f"ACI {aci}: unknown validation_status '{status}'")

        return warnings


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

_MAPPER_CACHE: ColorMapper | None = None


def load_default() -> ColorMapper:
    """Load default ColorMapper (cached)."""
    global _MAPPER_CACHE
    if _MAPPER_CACHE is None:
        _MAPPER_CACHE = ColorMapper.load()
    return _MAPPER_CACHE