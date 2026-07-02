# vcf_color_service

[![CI](https://github.com/outpost2026/vcf_color_service/actions/workflows/ci.yml/badge.svg)](https://github.com/outpost2026/vcf_color_service/actions/workflows/ci.yml)

Single source of truth for ACI color mapping across VCF/CNC projects.

ACI→RGB mapping, ACI→VCF parameter mapping, layer validation tools.

## Status

| Metric | Value |
|--------|-------|
| Tests | 24/24 PASS |
| Config | mode_value (statistical extraction from 35 customer VCFs) |
| Dependencies | none (pure Python) |

## Usage

```python
from vcf_color_service import ColorMapper

cm = ColorMapper.load()
rgb = cm.aci_to_rgb(1)        # (255, 0, 0)
name = cm.aci_to_name(1)      # "Red"
params = cm.aci_to_vcf_params(1)  # cutter, speed, h1, h2...
```

## License

MIT
