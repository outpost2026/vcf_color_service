#!/usr/bin/env python3
# vcf_color_extractor.py — Statisticka extrakce ACI mapovani z VCF souboru.
#
# Aggregates layer parameters from all available VCF files into a statistical
# database for building authoritative ACI->VCF parameter mapping.
#
# Usage:
#     python scripts/vcf_color_extractor.py [--output-dir ./output]

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

# Ensure vcf_parser_b2b is on path
_B2B = Path(__file__).resolve().parents[2] / "vcf_parser_b2b" / "src"
sys.path.insert(0, str(_B2B))

try:
    from vcf_binary_reader import extract_active_layers_details
except ImportError:
    print("ERROR: Cannot import vcf_binary_reader. "
          "Ensure vcf_parser_b2b/src/ is available.")
    sys.exit(1)

try:
    from vcf_color_service import ColorMapper
    _MAPPER = ColorMapper.load()
except ImportError:
    _MAPPER = None


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

SCAN_DIRS = [
    "C:/Users/PC/Documents/Repozitar_Dev/_github/VCF_files_moodpasta",
]
EXCLUDE_SUBSTR = []


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _is_excluded(path: str) -> bool:
    for sub in EXCLUDE_SUBSTR:
        if sub in path:
            return True
    return False


def find_vcf_files() -> list[Path]:
    found: dict[str, Path] = {}
    for d in SCAN_DIRS:
        root = Path(d)
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if _is_excluded(str(p)):
                continue
            if p.suffix.upper() != ".VCF":
                continue
            key = p.name.upper()  # dedup by filename
            if key not in found:
                found[key] = p
    return sorted(found.values(), key=lambda p: p.name)


def file_hash(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _mode(values: list) -> tuple:
    """Return (most_common_value, count, total)."""
    if not values:
        return ("", 0, 0)
    counts = defaultdict(int)
    for v in values:
        counts[v] += 1
    best = max(counts, key=counts.get)
    return (best, counts[best], len(values))


def _mode_of_values(values: list[float], as_int: bool = False) -> dict:
    """Return mode dict {value, count, total, ratio}.
    
    If as_int=True, round values to int before finding mode (for speed).
    If as_int=False, use raw values (for H1, H2, extension).
    """
    if not values:
        return {"value": None, "count": 0, "total": 0, "ratio": 0.0}
    processed = [round(v) if as_int else v for v in values]
    counts = defaultdict(int)
    for v in processed:
        counts[v] += 1
    best = max(counts, key=counts.get)
    return {
        "value": round(best, 3) if not as_int else int(best),
        "count": counts[best],
        "total": len(values),
        "ratio": round(counts[best] / len(values), 3),
    }


def _fmt_conf(count: int, std: float, range_val: float, cap: float = 1.0) -> float:
    """Heuristic confidence: more samples + lower std = higher confidence."""
    if count == 0:
        return 0.0
    n_factor = min(count / 20.0, 1.0) * 0.4
    std_factor = max(0.0, 1.0 - (std / max(range_val, 0.01)) * 2) * 0.4
    base = n_factor + std_factor + 0.2
    return round(min(base, cap), 3)


# ------------------------------------------------------------------
# Field extractors
# ------------------------------------------------------------------

EXTRACT_FIELDS = [
    "speed_mms",
    "cutter_type",
    "cutter_type_id",
    "number_of_feeding",
    "start_height_h1_mm",
    "end_height_h2_mm",
    "direction",
    "direction_id",
    "v_slot_width_comp_mm",
    "starting_extension_mm",
    "ending_extension_mm",
    "is_output_yes",
]

NUMERIC_FIELDS = {
    "speed_mms", "number_of_feeding", "start_height_h1_mm",
    "end_height_h2_mm", "v_slot_width_comp_mm",
    "starting_extension_mm", "ending_extension_mm",
}

CATEGORICAL_FIELDS = {
    "cutter_type", "direction", "is_output_yes",
}


# ------------------------------------------------------------------
# Core extraction
# ------------------------------------------------------------------

def extract_all() -> dict:
    """Scan all VCF files and aggregate layer data by color_val."""
    files = find_vcf_files()
    print(f"Found {len(files)} unique VCF files")

    # Raw records: list of (source_file, layer_dict)
    raw_records: list[dict] = []
    errors: list[tuple[str, str]] = []

    hashes_seen: set[str] = set()

    for fpath in files:
        fhash = file_hash(fpath)
        if fhash in hashes_seen:
            continue
        hashes_seen.add(fhash)

        try:
            with open(fpath, "rb") as f:
                data = f.read()
            layers = extract_active_layers_details(data)
            for layer in layers:
                layer["_source"] = str(fpath)
                layer["_source_name"] = fpath.name
                layer["_file_hash"] = fhash
                raw_records.append(layer)
        except Exception as e:
            errors.append((str(fpath), str(e)))

    print(f"  Hash-unique files: {len(hashes_seen)}")
    print(f"  Total layer records: {len(raw_records)}")
    print(f"  Parse errors: {len(errors)}")

    # Group by color_val (the raw uint32 from VCF)
    groups: dict[int, list[dict]] = defaultdict(list)
    for rec in raw_records:
        cv = rec.get("color_val", 0)
        groups[cv].append(rec)

    # Build statistics per color_val
    stats = {}
    for cv in sorted(groups.keys()):
        recs = groups[cv]
        n = len(recs)
        sample = recs[0]
        hex_str = sample.get("color_hex", f"0x{cv:08x}")
        rgb = sample.get("color_rgb", [0, 0, 0])

        # ACI mapping
        aci = None
        aci_name = None
        aci_conf = 0.0
        if _MAPPER:
            aci = _MAPPER.rgb_to_aci(rgb[0], rgb[1], rgb[2])
            aci_name = _MAPPER.aci_to_name(aci)
            # Check distance
            ar, ag, ab = _MAPPER.aci_to_rgb(aci)
            dist = math.sqrt((rgb[0]-ar)**2 + (rgb[1]-ag)**2 + (rgb[2]-ab)**2)
            aci_conf = max(0.0, 1.0 - dist / 441.67)  # normalized to [0,1]

        entry = {
            "color_val": cv,
            "color_hex": hex_str,
            "color_rgb": rgb,
            "aci_mapped": aci,
            "aci_name": aci_name,
            "aci_confidence": round(aci_conf, 3),
            "sample_count": n,
            "unique_sources": len(set(r["_source"] for r in recs)),
            "source_files": sorted(set(r["_source_name"] for r in recs)),
        }

        # Per-field statistics
        for field in EXTRACT_FIELDS:
            values = [r.get(field) for r in recs if r.get(field) is not None]
            if field in NUMERIC_FIELDS:
                vals = [float(v) for v in values if isinstance(v, (int, float))]
                if vals:
                    mn = min(vals)
                    mx = max(vals)
                    avg = _mean(vals)
                    std = _stdev(vals)
                    use_int_mode = (field == "speed_mms")
                    mode = _mode_of_values(vals, as_int=use_int_mode)
                    entry[field] = {
                        "mean": round(avg, 2),
                        "min": round(mn, 2),
                        "max": round(mx, 2),
                        "std": round(std, 2),
                        "count": len(vals),
                        "confidence": _fmt_conf(len(vals), std, max(mx - mn, 0.1)),
                        "mode_value": mode["value"],
                        "mode_count": mode["count"],
                        "mode_ratio": mode["ratio"],
                    }
                else:
                    entry[field] = None
            elif field in CATEGORICAL_FIELDS:
                vals = [str(v) for v in values]
                if vals:
                    mc, mcnt, tot = _mode(vals)
                    entry[field] = {
                        "most_common": mc,
                        "mode_count": mcnt,
                        "total": tot,
                        "mode_ratio": round(mcnt / max(tot, 1), 3),
                        "unique_values": sorted(set(vals)),
                    }
                else:
                    entry[field] = None

        stats[cv] = entry

    return {
        "meta": {
            "total_files_found": len(files),
            "hash_unique_files": len(hashes_seen),
            "total_layer_records": len(raw_records),
            "unique_colors": len(stats),
            "parse_errors": len(errors),
            "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mapper_available": _MAPPER is not None,
        },
        "errors": [{"file": e[0], "error": e[1]} for e in errors],
        "colors": stats,
    }


# ------------------------------------------------------------------
# Output
# ------------------------------------------------------------------

def write_report(data: dict, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = data["meta"]

    # Full JSON
    json_path = out_dir / "aci_statistics_full.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nFull JSON: {json_path}")

    # Summary CSV
    csv_path = out_dir / "aci_statistics_summary.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "color_hex", "color_rgb", "aci", "aci_name", "aci_conf",
            "samples", "sources",
            "speed_mean", "speed_mode", "speed_conf", "speed_range",
            "cutter_mode", "cutter_ratio",
            "direction_mode", "direction_ratio",
            "h1_mean", "h1_mode", "h2_mean", "h2_mode",
            "start_ext_mean", "start_ext_mode",
            "end_ext_mean", "end_ext_mode",
            "is_output_mode",
        ])
        for cv in sorted(data["colors"].keys()):
            c = data["colors"][cv]
            rgb = c["color_rgb"]
            sp = c.get("speed_mms") or {}
            ct = c.get("cutter_type") or {}
            dr = c.get("direction") or {}
            h1 = c.get("start_height_h1_mm") or {}
            h2 = c.get("end_height_h2_mm") or {}
            se = c.get("starting_extension_mm") or {}
            ee = c.get("ending_extension_mm") or {}
            io = c.get("is_output_yes") or {}
            writer.writerow([
                c["color_hex"], f"({rgb[0]},{rgb[1]},{rgb[2]})",
                c["aci_mapped"], c["aci_name"], c["aci_confidence"],
                c["sample_count"], c["unique_sources"],
                sp.get("mean", ""), sp.get("mode_value", ""),
                sp.get("confidence", ""),
                f"{sp.get('min','')}-{sp.get('max','')}" if sp else "",
                ct.get("most_common", ""), ct.get("mode_ratio", ""),
                dr.get("most_common", ""), dr.get("mode_ratio", ""),
                h1.get("mean", ""), h1.get("mode_value", ""),
                h2.get("mean", ""), h2.get("mode_value", ""),
                se.get("mean", ""), se.get("mode_value", ""),
                ee.get("mean", ""), ee.get("mode_value", ""),
                io.get("most_common", ""),
            ])
    print(f"Summary CSV: {csv_path}")

    # Human-readable report
    report_path = out_dir / "aci_statistics_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# ACI Color Mapping — Statistická analýza\n\n")
        f.write(f"**Datum:** {meta['extracted_at']}  \n")
        f.write(f"**Unikátní VCF soubory:** {meta['hash_unique_files']}  \n")
        f.write(f"**Celkem layer záznamů:** {meta['total_layer_records']}  \n")
        f.write(f"**Unikátních barev:** {meta['unique_colors']}  \n")
        f.write(f"**Parse chyb:** {meta['parse_errors']}  \n\n")

        f.write("## Per-color Statistics\n\n")
        f.write("| Hex | RGB | ACI | Název | Samples | Speed | Cutter | Direction | H1 | H2 | Ext.start | Ext.end | Conf |\n")
        f.write("|-----|-----|-----|-------|---------|-------|--------|-----------|----|----|-----------|---------|------|\n")

        for cv in sorted(data["colors"].keys()):
            c = data["colors"][cv]
            sp = c.get("speed_mms") or {}
            ct = c.get("cutter_type") or {}
            dr = c.get("direction") or {}
            h1 = c.get("start_height_h1_mm") or {}
            h2 = c.get("end_height_h2_mm") or {}
            se = c.get("starting_extension_mm") or {}
            ee = c.get("ending_extension_mm") or {}
            sp_str = f"{sp.get('mean','?')} ({sp.get('mode_value','?')})"
            ct_str = ct.get("most_common", "?")
            dr_str = dr.get("most_common", "?")
            h1_str = f"{h1.get('mean','?')} ({h1.get('mode_value','?')})" if h1 else "?"
            h2_str = f"{h2.get('mean','?')} ({h2.get('mode_value','?')})" if h2 else "?"
            se_str = f"{se.get('mean','?')} ({se.get('mode_value','?')})" if se else "?"
            ee_str = f"{ee.get('mean','?')} ({ee.get('mode_value','?')})" if ee else "?"
            conf = sp.get("confidence", 0) if sp else 0
            f.write(
                f"| {c['color_hex']} | {c['color_rgb']} "
                f"| {c['aci_mapped'] or '?'} | {c['aci_name'] or '?'} "
                f"| {c['sample_count']} | {sp_str} "
                f"| {ct_str} | {dr_str} | {h1_str} | {h2_str} "
                f"| {se_str} | {ee_str} | {conf} |\n"
            )

        f.write("\n## Per-Tool Mode Analysis\n\n")
        colors = data["colors"]
        tool_groups: dict[str, list[dict]] = {}
        for c in colors.values():
            ct = c.get("cutter_type") or {}
            tool = ct.get("most_common", "Unknown")
            tool_groups.setdefault(tool, []).append(c)

        for tool_name in sorted(tool_groups.keys()):
            entries = tool_groups[tool_name]
            f.write(f"### {tool_name} ({len(entries)} barev)\n\n")
            f.write("| ACI | Barva | Parametr | Mode hodnota | Sample count |\n")
            f.write("|-----|-------|----------|-------------|--------------|\n")
            for c in sorted(entries, key=lambda x: x["sample_count"], reverse=True):
                aci = c.get("aci_mapped") or "?"
                name = c.get("aci_name") or "?"
                sp = c.get("speed_mms") or {}
                h1 = c.get("start_height_h1_mm") or {}
                h2 = c.get("end_height_h2_mm") or {}
                se = c.get("starting_extension_mm") or {}
                ee = c.get("ending_extension_mm") or {}
                n = c["sample_count"]
                f.write(
                    f"| {aci} | {name} | Speed (mm/s) | {sp.get('mode_value','?')} | {n} |\n"
                )
                f.write(
                    f"| {aci} | {name} | H1 (mm) | {h1.get('mode_value','?')} | {n} |\n"
                )
                f.write(
                    f"| {aci} | {name} | H2 (mm) | {h2.get('mode_value','?')} | {n} |\n"
                )
                if se.get("mode_value") is not None and se["mode_value"] != 0:
                    f.write(
                        f"| {aci} | {name} | Ext.start (mm) | {se.get('mode_value','?')} | {n} |\n"
                    )
                if ee.get("mode_value") is not None and ee["mode_value"] != 0:
                    f.write(
                        f"| {aci} | {name} | Ext.end (mm) | {ee.get('mode_value','?')} | {n} |\n"
                    )
            f.write("\n")

        f.write("\n## Confidence Ranking\n\n")
        ranked = sorted(
            data["colors"].values(),
            key=lambda c: (
                c.get("speed_mms", {}) or {}
            ).get("confidence", 0),
            reverse=True,
        )
        for i, c in enumerate(ranked[:10], 1):
            sp = c.get("speed_mms") or {}
            f.write(
                f"{i}. **{c['color_hex']}** (ACI {c['aci_mapped']}) — "
                f"conf={sp.get('confidence', 0)}, "
                f"samples={c['sample_count']}, "
                f"speed={sp.get('mean','?')} (mode={sp.get('mode_value','?')})±{sp.get('std','?')}\n"
            )

        if data["errors"]:
            f.write("\n## Parse Errors\n\n")
            for e in data["errors"]:
                f.write(f"- `{e['file']}`: {e['error']}\n")

    print(f"Report: {report_path}")


def generate_updated_config(data: dict, out_dir: Path) -> dict:
    """Generate updated config.json based on statistical findings."""
    colors = data["colors"]

    updated = {
        "_schema": "aci_color_map_v2.1",
        "_description": (
            "Statisticky odvozený jediný zdroj pravdy pro ACI barevné mapování. "
            "Vygenerováno z {count} VCF souborů ({records} layer záznamů)."
        ).format(
            count=data["meta"]["hash_unique_files"],
            records=data["meta"]["total_layer_records"],
        ),
        "_version": "2.1",
        "_generated": data["meta"]["extracted_at"],
        "_generator": "vcf_color_extractor.py",
        "colors": {},
        "cutter_types": {
            "Vibrate cutter": {"id": 1, "description": "Oscilační / vibrační nůž"},
            "Wheel": {"id": 2, "description": "Kolečko (lamino)"},
            "Milling cutter": {"id": 3, "description": "Fréza"},
            "V-slot": {"id": 4, "description": "V-drážka (45° nůž)"},
            "Vibrate cut": {"id": 5, "description": "Alternativní vibrační řez"},
        },
        "directions": {
            "Left": {"id": 1, "description": "Jednostranný řez vlevo"},
            "Right": {"id": 2, "description": "Jednostranný řez vpravo"},
            "Cut both side": {"id": 3, "description": "Oboustranný řez (tam i zpět)"},
            "N/A": {"id": 0, "description": "Nerelevantní (Vibrate cutter)"},
        },
    }

    for cv in sorted(colors.keys()):
        c = colors[cv]
        sp = c.get("speed_mms") or {}
        ct = c.get("cutter_type") or {}
        dr = c.get("direction") or {}
        h1 = c.get("start_height_h1_mm") or {}
        h2 = c.get("end_height_h2_mm") or {}
        vs = c.get("v_slot_width_comp_mm") or {}
        se = c.get("starting_extension_mm") or {}
        ee = c.get("ending_extension_mm") or {}
        io = c.get("is_output_yes") or {}

        # Determine validation status from confidence
        conf = sp.get("confidence", 0) if sp else 0
        n = c["sample_count"]
        if n >= 5 and conf >= 0.7:
            valid_status = "calibrated"
        elif n >= 3:
            valid_status = "native_vcf"
        elif n >= 1:
            valid_status = "hypothesis"
        else:
            valid_status = "unknown"

        # Use mapper for names if available
        aci = c.get("aci_mapped")
        if aci is not None and _MAPPER:
            name_cs = _MAPPER.aci_to_name(aci, "cs")
            name_en = _MAPPER.aci_to_name(aci, "en")
            ref_rgb = list(_MAPPER.aci_to_rgb(aci))
        else:
            name_cs = f"Color_{cv:06x}"
            name_en = f"Color_{cv:06x}"
            ref_rgb = c["color_rgb"]

        aci_key = str(aci) if aci is not None else f"custom_{cv:06x}"

        updated["colors"][aci_key] = {
            "name_cs": name_cs,
            "name_en": name_en,
            "rgb": ref_rgb,
            "vcf_params": {
                "cutter_type": ct.get("most_common", "Vibrate cutter"),
                "speed_mms": round(sp.get("mode_value", sp.get("mean", 200))) if sp else 200,
                "direction": dr.get("most_common", "N/A"),
                "h1_mm": round(h1.get("mode_value", h1.get("mean", 2.0)), 1) if h1 else 2.0,
                "h2_mm": round(h2.get("mode_value", h2.get("mean", -0.3)), 1) if h2 else -0.3,
                "vs_comp_mm": round(vs.get("mode_value", vs.get("mean", 0.0)), 2) if vs else 0.0,
                "start_extension_mm": round(se.get("mode_value", se.get("mean", 0.0)), 1) if se else 0.0,
                "end_extension_mm": round(ee.get("mode_value", ee.get("mean", 0.0)), 1) if ee else 0.0,
                "is_output": io.get("most_common", "True") == "True",
            },
            "validation_status": valid_status,
            "_stats": {
                "sample_count": c["sample_count"],
                "source_count": c["unique_sources"],
                "speed_mean": sp.get("mean", 0) if sp else 0,
                "speed_std": sp.get("std", 0) if sp else 0,
                "speed_mode": sp.get("mode_value", 0) if sp else 0,
                "speed_range": f"{sp.get('min','?')}-{sp.get('max','?')}" if sp else "?",
                "confidence_score": conf,
            },
        }

    config_path = out_dir / "config_generated.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2, ensure_ascii=False)
    print(f"Generated config: {config_path}")

    return updated


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Extract ACI color mapping statistics from VCF files"
    )
    ap.add_argument("--output-dir", "-o",
                    default=Path(__file__).resolve().parent / "color_extraction_output")
    args = ap.parse_args()
    out_dir = Path(args.output_dir)

    print("=" * 60)
    print("VCF Color Extractor — Statistical ACI Analysis")
    print("=" * 60)

    data = extract_all()
    write_report(data, out_dir)
    generate_updated_config(data, out_dir)

    print("\nDONE.")


if __name__ == "__main__":
    main()