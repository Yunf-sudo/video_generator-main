from __future__ import annotations


def build_prompt_context(meta: dict | None = None) -> dict[str, str]:
    meta = meta or {}

    brand_name = str(meta.get("product_brand_name") or meta.get("brand_name") or "").strip()
    product_name = str(meta.get("product_name") or "").strip()
    marketing_product_name = str(meta.get("marketing_product_name") or product_name or brand_name or "").strip()
    hero_product_name = str(
        meta.get("hero_product_name")
        or product_name
        or (f"{brand_name} 电动轮椅" if brand_name else "本次主推电动轮椅")
    ).strip()

    use_reference_images = bool(meta.get("use_product_reference_images", True))
    if use_reference_images:
        reference_image_instruction = (
            "如果提供了官方产品参考图、多视角拼版参考图、产品参考签名或产品结构信息，请把它们当作跨场景保持一致的视觉参考，"
            "优先吸收已经被参考图证实的产品身份特征与比例关系，但要结合当前镜头自然转化，而不是生硬照抄或机械枚举。"
            "如果某张参考图只覆盖局部结构，例如摇杆细节、后轮与底盘连接件、底盘交叉支撑或座椅下方开放结构，只把它当成对应可见部位的局部硬锚点，不要让局部特写改写整车整体比例。"
            "不要脑补参考图里看不见的隐藏结构。不要在广告里复现拼版标签、分隔线、白底棚拍背景，也不要插入产品页 packshot。"
        )
    else:
        reference_image_instruction = (
            "当前任务没有提供官方产品参考图包，因此你需要在所有场景里保持同一台高质感电动轮椅的身份一致，"
            "但不要假装自己在逐像素匹配某张产品图。"
        )

    return {
        "brand_name": brand_name or "品牌方",
        "marketing_product_name": marketing_product_name or hero_product_name,
        "hero_product_name": hero_product_name or "本次主推电动轮椅",
        "reference_image_instruction": reference_image_instruction,
    }
