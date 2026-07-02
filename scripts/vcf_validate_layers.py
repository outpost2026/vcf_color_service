#!/usr/bin/env python3
"""vcf_validate_layers.py — Validation gate pro VCF pipeline.

Detekuje anomálie v přiřazení ACI barev vůči statistickému ground truth.
Při nalezení nestandardního párování (např. ACI 1/Červená + V-slot) vypíše
varování a při --strict režimu vrací exit code 1 (= zastavení pipeline).

Usage:
    python scripts/vcf_validate_layers.py <file.vcf> [--strict] [--json]
    python scripts/vcf_validate_layers.py --dir ./vcf_output/ [--strict]
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from vcf_color_service import ColorMapper
    _MAPPER = ColorMapper.load()
except ImportError:
    _MAPPER = None

try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vcf_parser_b2b" / "src"))
    from vcf_binary_reader import extract_active_layers_details
except ImportError:
    extract_active_layers_details = None


# ---------------------------------------------------------------------------
# Whitelist: povolené kombinace (ACI → cutter_type)
# Každá ACI barva má očekávaný cutter. Cokoliv mimo = anomálie.
# ---------------------------------------------------------------------------
#
# Zdroj: statistická extrakce z 35 customer VCF (98 layer záznamů)
#
EXPECTED_CUTTER = {
    0:  "Vibrate cutter",     # Černá — vždy Vibrate (30/30, ratio 0.967)
    1:  "Vibrate cutter",     # Červená — převážně Vibrate (5/8)
    2:  "Vibrate cutter",     # Žlutá — převážně Vibrate (2/3)
    3:  "V-slot",             # Zelená — vždy V-slot (15/15)
    4:  "V-slot",             # Azurová — vždy V-slot (9/9)
    5:  "Vibrate cutter",     # Modrá — převážně Vibrate (8/11)
    6:  "Vibrate cutter",     # Purpurová — vzorky jen Vibrate
    7:  "Vibrate cutter",     # Černá alias
    8:  "V-slot",             # Tmavě šedá — jeden vzorek V-slot
    30: "Vibrate cutter",     # Oranžová — oba vzorky Vibrate
    52: "V-slot",             # Tyrkysová — vždy V-slot (6/6)
    92: "V-slot",             # Azurová tmavá — jeden vzorek V-slot
}

EXPECTED_DIRECTION = {
    0:  "N/A",
    1:  "N/A",
    2:  "N/A",
    3:  "Cut both side",
    4:  "Left",
    5:  "N/A",
    6:  "N/A",
    7:  "N/A",
    30: "N/A",
    52: "Cut both side",
}


def resolve_aci(color_val: int, rgb: list) -> int:
    """color_val nebo RGB → ACI číslo."""
    if _MAPPER:
        return _MAPPER.rgb_to_aci(rgb[0], rgb[1], rgb[2])
    if color_val == 0:
        return 0
    return color_val  # fallback


def validate_file(path: Path, strict: bool = False) -> list[dict]:
    """Validate one VCF file. Returns list of anomaly records."""
    anomalies = []
    with open(path, "rb") as f:
        data = f.read()
    if extract_active_layers_details is None:
        return [{"error": "vcf_binary_reader not available"}]
    layers = extract_active_layers_details(data)
    for layer in layers:
        color_val = layer.get("color_val", 0)
        rgb = layer.get("color_rgb", [0, 0, 0])
        aci = resolve_aci(color_val, rgb)
        cutter = layer.get("cutter_type", "")
        direction = layer.get("direction", "")
        speed = layer.get("speed_mms", 0)

        entry = {
            "aci": aci,
            "color_hex": layer.get("color_hex", f"0x{color_val:08x}"),
            "color_rgb": rgb,
            "cutter_actual": cutter,
            "speed_actual": speed,
            "direction_actual": direction,
        }

        # Check cutter
        expected = EXPECTED_CUTTER.get(aci)
        if expected and cutter != expected:
            entry["issue"] = f"cutter_mismatch"
            entry["cutter_expected"] = expected
            entry["severity"] = "error" if strict else "warning"
            anomalies.append(entry)
            continue

        # Check direction
        exp_dir = EXPECTED_DIRECTION.get(aci)
        if exp_dir and direction != exp_dir:
            entry["issue"] = f"direction_mismatch"
            entry["direction_expected"] = exp_dir
            entry["severity"] = "warning"
            anomalies.append(entry)
            continue

    return anomalies


def main():
    ap = argparse.ArgumentParser(description="VCF Layer Validation Gate")
    ap.add_argument("target", nargs="?", help="VCF file or directory")
    ap.add_argument("--dir", help="Directory with VCF files")
    ap.add_argument("--strict", action="store_true",
                    help="Exit with code 1 on any anomaly")
    ap.add_argument("--json", action="store_true",
                    help="Output as JSON (silent on success)")
    args = ap.parse_args()

    # Collect files
    target = args.target or args.dir
    if not target:
        ap.print_help()
        sys.exit(1)

    target_path = Path(target)
    if target_path.is_dir():
        files = sorted(target_path.glob("*.VCF")) + sorted(target_path.glob("*.vcf"))
    else:
        files = [target_path]

    if not files:
        print("No VCF files found.")
        sys.exit(0)

    total_anomalies = 0
    results = {}

    for fpath in files:
        anomalies = validate_file(fpath, strict=args.strict)
        results[fpath.name] = {
            "file": str(fpath),
            "anomalies": anomalies,
            "count": len(anomalies),
        }
        total_anomalies += len(anomalies)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for fname, res in results.items():
            if res["count"] == 0:
                print(f"  [OK] {fname}")
            else:
                print(f"  [FAIL] {fname} — {res['count']} anomalie:")
                for a in res["anomalies"]:
                    sev = a.get("severity", "warning")
                    icon = "[ERR]" if sev == "error" else "[WARN]"
                    print(f"       {icon} ACI {a['aci']} {a['color_hex']}: {a['issue']}")
                    print(f"          aktuální: cutter={a['cutter_actual']}, směr={a['direction_actual']}")
                    if "cutter_expected" in a:
                        print(f"          očekáván: cutter={a['cutter_expected']}")

        print(f"\nCelkem: {len(files)} souborů, {total_anomalies} anomálií")

    if args.strict and total_anomalies > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
