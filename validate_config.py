"""
validate_config.py
------------------
quadruped_schema.json formatındaki bir config dosyasını doğrular.
compose_idle.py'yi çalıştırmadan ÖNCE config'i doldururken hataları yakalar.

Kullanım:
  python validate_config.py --config configs/needlecrawler.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List


def _strip_doc(obj):
    """'_doc' veya '_*_doc' key'lerini gezerken yoksay."""
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if not k.startswith("_")}
    return obj


def validate(cfg: dict) -> List[str]:
    """Hata listesi döndür. Boş liste = geçerli."""
    errors = []

    # Üst seviye
    for key in ("rig", "profile"):
        if key not in cfg:
            errors.append(f"Üst seviyede '{key}' bölümü eksik.")

    if errors:
        return errors  # yapısal hatadan sonra devam etme

    rig = _strip_doc(cfg["rig"])
    profile = _strip_doc(cfg["profile"])

    # Rig kontrolleri
    if "axes" not in rig:
        errors.append("rig.axes eksik.")
    else:
        axes = _strip_doc(rig["axes"])
        if axes.get("up") not in ("X", "Y", "Z", "-X", "-Y", "-Z"):
            errors.append(f"rig.axes.up geçersiz: {axes.get('up')}")
        if axes.get("forward") not in ("X", "Y", "Z", "-X", "-Y", "-Z"):
            errors.append(f"rig.axes.forward geçersiz: {axes.get('forward')}")
        scale = axes.get("unit_scale_to_meters")
        if not isinstance(scale, (int, float)) or scale <= 0:
            errors.append(f"rig.axes.unit_scale_to_meters pozitif sayı olmalı: {scale}")

    if "skeleton" not in rig:
        errors.append("rig.skeleton eksik.")
    else:
        skel = _strip_doc(rig["skeleton"])

        # Pelvis zorunlu
        if not skel.get("pelvis"):
            errors.append("rig.skeleton.pelvis zorunludur (en azından bir bone adı).")

        # Spine bone sayısı, profile.breathing.spine_distribution ile uyuşmalı
        spine = skel.get("spine") or []
        if not isinstance(spine, list):
            errors.append("rig.skeleton.spine bir array olmalı.")
        elif len(spine) == 0:
            errors.append("rig.skeleton.spine en az bir bone içermeli.")

        # Bacaklar
        for side_group in ("front_legs", "hind_legs"):
            if side_group not in skel:
                errors.append(f"rig.skeleton.{side_group} eksik.")
                continue
            legs = _strip_doc(skel[side_group])
            for side in ("left", "right"):
                if side not in legs:
                    errors.append(f"rig.skeleton.{side_group}.{side} eksik.")

    # Profile kontrolleri
    breathing = _strip_doc(profile.get("breathing", {}))
    if breathing:
        spine_dist = breathing.get("spine_distribution", [])
        spine_count = len(rig.get("skeleton", {}).get("spine", []) or [])
        if spine_count and len(spine_dist) != spine_count:
            errors.append(
                f"profile.breathing.spine_distribution uzunluğu ({len(spine_dist)}) "
                f"rig.skeleton.spine uzunluğuyla ({spine_count}) eşleşmiyor."
            )
        if spine_dist:
            total = sum(spine_dist)
            if not (0.8 <= total <= 1.2):
                errors.append(
                    f"profile.breathing.spine_distribution toplamı ~1.0 olmalı, "
                    f"şu anki toplam: {total:.3f}"
                )

    # Tail — varsa profile.tail_secondary_motion ile tutarlı olmalı
    tail = rig.get("skeleton", {}).get("tail", []) or []
    tail_motion = _strip_doc(profile.get("tail_secondary_motion", {}))
    if tail_motion and not tail:
        errors.append(
            "profile.tail_secondary_motion tanımlı ama rig.skeleton.tail boş. "
            "Kuyruk yoksa tail_secondary_motion'ı kaldır veya amplitude'u 0 yap."
        )

    # Leg twitch candidate bones gerçekten skeleton'da mı?
    twitch = _strip_doc(profile.get("leg_twitch", {}))
    if twitch.get("enabled"):
        candidates = twitch.get("candidate_bones", [])
        skel = rig.get("skeleton", {})
        all_bones = _collect_all_bones(skel)
        for bone in candidates:
            if bone and bone not in all_bones:
                errors.append(
                    f"profile.leg_twitch.candidate_bones içinde '{bone}' var "
                    f"ama rig.skeleton'da bulunamadı."
                )

    return errors


def _collect_all_bones(skel: dict) -> set:
    """Skeleton ağacındaki tüm bone isimlerini düz liste olarak topla."""
    bones = set()
    skel = _strip_doc(skel)
    for v in skel.values():
        if isinstance(v, str):
            bones.add(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    bones.add(item)
        elif isinstance(v, dict):
            bones |= _collect_all_bones(v)
    return bones


def main():
    parser = argparse.ArgumentParser(description="Quadruped config validator")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)

    errors = validate(cfg)
    if not errors:
        print(f"[ok] Config geçerli: {args.config}")
        sys.exit(0)

    print(f"[hata] {len(errors)} sorun bulundu:", file=sys.stderr)
    for i, err in enumerate(errors, 1):
        print(f"  {i}. {err}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
