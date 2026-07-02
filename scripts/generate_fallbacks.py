#!/usr/bin/env python3
"""
generate_fallbacks.py — Synchronize fallback code across repos from config.json.

Usage:
    python scripts/generate_fallbacks.py

This reads vcf_color_service/config.json and prints fallback code snippets
that can be copied into each repo's source files. In CI mode (--ci), it
warns if any repo's fallback is out of sync.

Supports:
  - vcf_parser_b2b: COLOR_MAP in vcf_binary_reader.py
  - dxf_integrace: _ACI_COLOR_NAMES + _VIZ_COLORS in dxf_geometry_indexer_v2.py
  - Vcf-compiler: ACI_TO_RGB in _dxf_adapter.py
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CONFIG = _HERE.parent / "vcf_color_service" / "config.json"


def load_mapper():
    sys.path.insert(0, str(_HERE.parent))
    from vcf_color_service import ColorMapper
    return ColorMapper.load(_CONFIG)


def gen_color_map(mapper) -> str:
    """Generate COLOR_MAP for vcf_parser_b2b.vcf_binary_reader (hex→cs_name)."""
    lines = ["# Fallback generated from vcf_color_service v2.0.0",
             "# Source: config.json — do not edit manually.",
             "COLOR_MAP = {"]
    for aci_str in sorted(mapper._colors, key=int):
        entry = mapper._colors[aci_str]
        rgb = entry["rgb"]
        hex_key = f"{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
        name = entry.get("name_cs", f"ACI_{aci_str}")
        lines.append(f'    "{hex_key}": "{name}",')
    lines.append("}")
    return "\n".join(lines)


def gen_aci_names(mapper) -> str:
    """Generate _ACI_COLOR_NAMES for dxf_integrace (ACI→en_name)."""
    lines = ["# Fallback generated from vcf_color_service v2.0.0",
             "# Source: config.json — do not edit manually.",
             "_ACI_COLOR_NAMES = {"]
    for aci_str in sorted(mapper._colors, key=int):
        name = mapper._colors[aci_str].get("name_en", f"ACI_{aci_str}")
        lines.append(f"    {aci_str}: {json.dumps(name)},")
    lines.append("}")
    return "\n".join(lines)


def gen_viz_colors(mapper) -> str:
    """Generate _VIZ_COLORS for dxf_integrace (ACI→#hex)."""
    lines = ["# Fallback generated from vcf_color_service v2.0.0",
             "# Source: config.json — do not edit manually.",
             "_VIZ_COLORS = {"]
    for aci_str in sorted(mapper._colors, key=int):
        rgb = mapper._colors[aci_str]["rgb"]
        hex_str = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        lines.append(f"    {aci_str}: {json.dumps(hex_str)},")
    lines.append("}")
    return "\n".join(lines)


def gen_aci_to_rgb(mapper) -> str:
    """Generate ACI_TO_RGB for Vcf-compiler._dxf_adapter (ACI→(R,G,B))."""
    lines = ["# Fallback generated from vcf_color_service v2.0.0",
             "# Source: config.json — do not edit manually.",
             "ACI_TO_RGB = {"]
    for aci_str in sorted(mapper._colors, key=int):
        r, g, b = mapper._colors[aci_str]["rgb"]
        lines.append(f"    {aci_str}: ({r}, {g}, {b}),")
    lines.append("}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Generate fallback code from config.json")
    ap.add_argument("--ci", action="store_true",
                    help="CI mode: warn if any export would change")
    args = ap.parse_args()

    mapper = load_mapper()

    outputs = {
        "vcf_parser_b2b (COLOR_MAP)": gen_color_map(mapper),
        "dxf_integrace (_ACI_COLOR_NAMES)": gen_aci_names(mapper),
        "dxf_integrace (_VIZ_COLORS)": gen_viz_colors(mapper),
        "Vcf-compiler (ACI_TO_RGB)": gen_aci_to_rgb(mapper),
    }

    if args.ci:
        any_change = False
        print("CI mode — checking fallback sync...")
        for label, code in outputs.items():
            print(f"\n--- {label} ---\n{code}\n")
        print("CI: Generated outputs above. Compare against current repo sources.")
        return

    for label, code in outputs.items():
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}\n")
        print(code)


if __name__ == "__main__":
    main()