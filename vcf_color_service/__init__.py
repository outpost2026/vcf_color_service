"""
vcf_color_service — ACI Color Service.

Single source of truth for ACI (AutoCAD Color Index) color mapping
across vcf_parser_b2b, dxf_integrace and Vcf-compiler repositories.

Usage:
    from vcf_color_service import ColorMapper

    mapper = ColorMapper.load()
    rgb = mapper.aci_to_rgb(7)            # → (0, 0, 0)
    name = mapper.aci_to_name(52, "cs")   # → "Tyrkysová"
    params = mapper.aci_to_vcf_params(3)  # → {speed_mms: 300, ...}
"""

from .core import ColorMapper, load_default

__all__ = ["ColorMapper", "load_default"]
