from __future__ import annotations


def build_prompt_context(meta: dict | None = None) -> dict[str, str]:
    meta = meta or {}

    brand_name = str(meta.get("product_brand_name") or meta.get("brand_name") or "").strip()
    product_name = str(meta.get("product_name") or "").strip()
    marketing_product_name = str(meta.get("marketing_product_name") or product_name or brand_name or "").strip()
    hero_product_name = str(
        meta.get("hero_product_name")
        or product_name
        or (f"{brand_name} powered wheelchair" if brand_name else "the featured powered wheelchair")
    ).strip()

    use_reference_images = bool(meta.get("use_product_reference_images", True))
    if use_reference_images:
        reference_image_instruction = (
            "When official product reference images, a product reference signature, or a product visual structure are "
            "provided, treat them as visual guidance for consistency across scenes, but adapt them naturally for the "
            "current shot instead of copying them literally. Never reproduce the white studio background or insert a "
            "product-photo packshot into the ad."
        )
    else:
        reference_image_instruction = (
            "No official product reference image pack is provided for this task, so keep one consistent premium powered "
            "wheelchair identity across every scene without claiming an exact product-photo match."
        )

    return {
        "brand_name": brand_name or "the brand",
        "marketing_product_name": marketing_product_name or hero_product_name,
        "hero_product_name": hero_product_name or "the featured powered wheelchair",
        "reference_image_instruction": reference_image_instruction,
    }
