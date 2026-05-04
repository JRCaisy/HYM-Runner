"""
compose_idle.py
---------------
Quadruped rig config + energy curve (opsiyonel HY-Motion) ile
procedural idle animasyonu üretir. BVH formatında export eder.

Mimari:
  1. Config'den rig yapısını ve profile parametrelerini oku
  2. Energy curve'ü yükle (HY-Motion veya flat)
  3. Procedural katmanları üret:
     a) Breathing — sin dalgası, chest offset
     b) Head micro-motion — yaw/pitch, energy-modulated
     c) Tail secondary — breathing'den gecikmeli dalga
     d) Ear twitch — random sparse events
     e) Leg twitch — random sparse events
     f) Weight shift — breathing'e faz kaydırmalı
  4. Loop seal — cosine blend
  5. BVH export

NeedleCrawler hiyerarşi notu:
  Ön bacaklar chest'in child'ıdır. Chest breathing hareketi ön bacakları
  doğal olarak hareket ettirir. Ön bacaklara ters kompanzasyon uygulanır
  ki ayaklar yere sabitlenmiş kalsın.

Kullanım:
  python compose_idle.py --config configs/needlecrawler.json --output idle.bvh
  python compose_idle.py --config configs/needlecrawler.json --energy curves_v08.json --output idle.bvh
  python compose_idle.py --config configs/needlecrawler.json --output idle.bvh --preview idle_preview.png

Bağımlılıklar: numpy, opsiyonel: matplotlib
"""

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG LOADER
# ═══════════════════════════════════════════════════════════════════════════════

def load_config(path: Path) -> Dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_energy_curve(path: Optional[Path]) -> Optional[np.ndarray]:
    """curves.json'dan energy_curve yükle. Yoksa None döner."""
    if path is None or not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if "energy_curve" in data:
        return np.array(data["energy_curve"])
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# PROCEDURAL GENERATORS
# ═══════════════════════════════════════════════════════════════════════════════

def gen_breathing(n_frames: int, fps: int, profile: Dict) -> np.ndarray:
    """
    Breathing curve üret. Çıktı shape: (n_frames,), aralık: -1..1
    Procedural: sin dalgası.
    """
    bp = profile.get("breathing", {})
    freq = bp.get("frequency_hz", 0.3)
    t = np.arange(n_frames) / fps
    # Sin dalgası: tam döngüler olsun ki loop dikişi kolay olsun
    # n_cycles'ı tam sayıya yuvarla
    duration = n_frames / fps
    n_cycles = max(1, round(duration * freq))
    actual_freq = n_cycles / duration
    curve = np.sin(2 * math.pi * actual_freq * t)
    return curve


def gen_head_motion(n_frames: int, fps: int, profile: Dict,
                    energy: Optional[np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """
    Head yaw ve pitch. Energy yüksekken amplitüd artar.
    Çıktı: (yaw_deg, pitch_deg), her biri (n_frames,)
    """
    hp = profile.get("head_micro_motion", {})
    yaw_amp = hp.get("yaw_amplitude_deg", 2.0)
    pitch_amp = hp.get("pitch_amplitude_deg", 1.5)
    freq = hp.get("frequency_hz", 0.4)
    phase = hp.get("phase_offset_rad", 0.7)
    e_mod = hp.get("energy_modulation", 0.6)

    t = np.arange(n_frames) / fps
    base_yaw = np.sin(2 * math.pi * freq * t)
    base_pitch = np.sin(2 * math.pi * freq * t + phase)

    if energy is not None and e_mod > 0:
        e_resampled = resample_curve(energy, n_frames)
        modulator = (1.0 - e_mod) + e_mod * e_resampled
    else:
        modulator = np.ones(n_frames)

    yaw = base_yaw * yaw_amp * modulator
    pitch = base_pitch * pitch_amp * modulator
    return yaw, pitch


def gen_tail_secondary(n_frames: int, fps: int, breathing: np.ndarray,
                       profile: Dict, n_tail_bones: int) -> np.ndarray:
    """
    Kuyruk secondary motion: breathing sinyalinin gecikmeli + sönümlü kopyası.
    Çıktı: (n_frames, n_tail_bones) derece cinsinden yaw açıları.
    """
    tp = profile.get("tail_secondary_motion", {})
    amp = tp.get("amplitude_deg", 4.0)
    delay = tp.get("delay_per_segment_frames", 2)
    damping = tp.get("damping", 0.7)

    if n_tail_bones == 0:
        return np.zeros((n_frames, 0))

    result = np.zeros((n_frames, n_tail_bones))
    for i in range(n_tail_bones):
        shift = delay * (i + 1)
        # Gecikmeli sinyal: kaydır, başı sıfırla
        shifted = np.roll(breathing, shift)
        shifted[:shift] = shifted[shift]
        bone_amp = amp * (damping ** i)
        result[:, i] = shifted * bone_amp

    return result


def gen_sparse_twitches(n_frames: int, fps: int,
                        events_per_min: float, max_amp_deg: float,
                        duration_frames: int, n_targets: int,
                        energy: Optional[np.ndarray],
                        energy_threshold: float,
                        rng: np.random.Generator) -> np.ndarray:
    """
    Sparse random twitch events.
    Çıktı: (n_frames, n_targets) derece cinsinden.
    """
    result = np.zeros((n_frames, n_targets))
    if n_targets == 0 or events_per_min <= 0:
        return result

    # Ortalama event aralığı (frame)
    avg_interval = int(60 * fps / events_per_min)
    if avg_interval < duration_frames * 2:
        avg_interval = duration_frames * 2

    e_resampled = resample_curve(energy, n_frames) if energy is not None else None

    frame = rng.integers(fps, min(avg_interval, n_frames))
    while frame < n_frames - duration_frames:
        # Energy threshold kontrolü
        if e_resampled is not None and e_resampled[frame] < energy_threshold:
            frame += rng.integers(fps // 2, fps)
            continue

        target = rng.integers(0, n_targets)
        amp = rng.uniform(0.3, 1.0) * max_amp_deg
        direction = rng.choice([-1, 1])

        # Smooth pulse: yarım sin dalgası
        pulse = np.sin(np.linspace(0, math.pi, duration_frames)) * amp * direction
        end = min(frame + duration_frames, n_frames)
        result[frame:end, target] += pulse[:end - frame]

        frame += rng.integers(avg_interval // 2, avg_interval * 2)

    return result


def gen_weight_shift(n_frames: int, fps: int, breathing: np.ndarray,
                     profile: Dict) -> np.ndarray:
    """
    Gövde yanal kaydırma: breathing'e faz kaydırmalı sin.
    Çıktı: (n_frames,) birim cinsinden offset.
    """
    ws = profile.get("weight_shift", {})
    if not ws.get("enabled", False):
        return np.zeros(n_frames)

    amp = ws.get("amplitude_units", 0.5)
    phase = ws.get("phase_shift_rad", math.pi / 2)

    # Breathing'in frekansını koru ama faz kaydır
    # Breathing zaten sin tabanlı, faz kaydırmak için Hilbert veya basit shift
    t = np.arange(n_frames) / fps
    duration = n_frames / fps
    bp = profile.get("breathing", {})
    freq = bp.get("frequency_hz", 0.3)
    n_cycles = max(1, round(duration * freq))
    actual_freq = n_cycles / duration
    shift = np.sin(2 * math.pi * actual_freq * t + phase)
    return shift * amp


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY
# ═══════════════════════════════════════════════════════════════════════════════

def resample_curve(curve: np.ndarray, target_len: int) -> np.ndarray:
    """1D curve'ü hedef uzunluğa lineer interpolasyonla resize et."""
    if len(curve) == target_len:
        return curve.copy()
    x_old = np.linspace(0, 1, len(curve))
    x_new = np.linspace(0, 1, target_len)
    return np.interp(x_new, x_old, curve)


def cosine_blend_loop(data: np.ndarray, blend_frames: int) -> np.ndarray:
    """
    İlk ve son frame'leri cosine blend ile eşleştir.
    data: (n_frames, ...) herhangi bir shape.
    """
    if blend_frames <= 0 or data.shape[0] < blend_frames * 2:
        return data

    result = data.copy()
    n = blend_frames

    # Cosine ağırlık: 0'dan 1'e (son frame'e yaklaştıkça başa doğru blend)
    weight = 0.5 * (1.0 - np.cos(np.linspace(0, math.pi, n)))

    for i in range(n):
        alpha = weight[i]
        # Son n frame'i: (1-alpha)*kendi + alpha*baştaki karşılığı
        result[-(n - i)] = (1 - alpha) * data[-(n - i)] + alpha * data[i]

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# BONE CHANNEL ASSEMBLY
# ═══════════════════════════════════════════════════════════════════════════════

class BoneAnim:
    """Tek bir bone'un frame bazlı rotation/translation verisini tutar."""
    def __init__(self, name: str, n_frames: int):
        self.name = name
        self.rot = np.zeros((n_frames, 3))   # (Xrot, Yrot, Zrot) derece
        self.pos = np.zeros((n_frames, 3))   # (Xpos, Ypos, Zpos) birim


def build_bone_anims(cfg: Dict, n_frames: int, fps: int,
                     energy: Optional[np.ndarray],
                     seed: int = 42) -> Dict[str, BoneAnim]:
    """
    Config'e göre tüm bone animation'ları üret.
    Dönen dict: bone_name → BoneAnim
    """
    profile = cfg["profile"]
    skel = cfg["rig"]["skeleton"]
    rng = np.random.default_rng(seed)

    anims: Dict[str, BoneAnim] = {}

    def get_or_create(name: str) -> BoneAnim:
        if name not in anims:
            anims[name] = BoneAnim(name, n_frames)
        return anims[name]

    # ── 1. BREATHING ──────────────────────────────────────────────────────
    breathing = gen_breathing(n_frames, fps, profile)
    bp = profile.get("breathing", {})
    chest_offset_amp = bp.get("chest_offset_amplitude_units", 1.0)
    chest_scale_amp = bp.get("chest_scale_amplitude", 0.01)

    # Up axis: config'den oku
    up_axis = cfg["rig"]["axes"].get("up", "Y")
    up_idx = {"X": 0, "Y": 1, "Z": 2}.get(up_axis, 1)

    # Chest breathing: yukarı-aşağı offset
    chest_name = skel["spine"][0] if skel.get("spine") else None
    if chest_name:
        a = get_or_create(chest_name)
        a.pos[:, up_idx] = breathing * chest_offset_amp
        # Chest'e küçük pitch (X rotation) ekle — nefes alırken hafif öne eğilme
        a.rot[:, 0] = breathing * 1.5  # derece

    # ── FRONT LEG KOMPANZASYONU ──────────────────────────────────────────
    # NeedleCrawler'da ön bacaklar chest'in child'ı.
    # Chest yukarı gidince ön bacaklar da gider → ayaklar yerden kalkar.
    # Bunu önlemek için frontleg shoulder'larına ters Y offset ver.
    for side_key in ("left", "right"):
        fl = skel.get("front_legs", {}).get(side_key, {})
        shoulder = fl.get("shoulder")
        if shoulder and chest_name:
            a = get_or_create(shoulder)
            a.pos[:, up_idx] = -breathing * chest_offset_amp

    # ── 2. HEAD MICRO-MOTION ─────────────────────────────────────────────
    head_name = skel.get("head")
    if head_name:
        yaw, pitch = gen_head_motion(n_frames, fps, profile, energy)
        a = get_or_create(head_name)
        a.rot[:, 1] += yaw    # Y rotation = yaw
        a.rot[:, 0] += pitch  # X rotation = pitch

    # ── 3. TAIL SECONDARY ────────────────────────────────────────────────
    tail_bones = skel.get("tail", [])
    if tail_bones:
        tail_motion = gen_tail_secondary(n_frames, fps, breathing, profile, len(tail_bones))
        for i, bone_name in enumerate(tail_bones):
            a = get_or_create(bone_name)
            a.rot[:, 1] += tail_motion[:, i]  # yaw (yanal sallanma)

    # ── 4. EAR TWITCH ────────────────────────────────────────────────────
    ear_cfg = profile.get("ear_twitch", {})
    if ear_cfg.get("enabled", False):
        ear_bones = ear_cfg.get("candidate_bones", [])
        if ear_bones:
            ear_twitches = gen_sparse_twitches(
                n_frames, fps,
                ear_cfg.get("events_per_minute", 5),
                ear_cfg.get("max_amplitude_deg", 6.0),
                ear_cfg.get("duration_frames", 4),
                len(ear_bones), energy,
                ear_cfg.get("energy_threshold", 0.2), rng
            )
            for i, bone_name in enumerate(ear_bones):
                a = get_or_create(bone_name)
                a.rot[:, 0] += ear_twitches[:, i]  # pitch

    # ── 5. LEG TWITCH ────────────────────────────────────────────────────
    leg_cfg = profile.get("leg_twitch", {})
    if leg_cfg.get("enabled", False):
        leg_bones = leg_cfg.get("candidate_bones", [])
        if leg_bones:
            leg_twitches = gen_sparse_twitches(
                n_frames, fps,
                leg_cfg.get("events_per_minute", 3),
                leg_cfg.get("max_amplitude_deg", 2.5),
                leg_cfg.get("duration_frames", 5),
                len(leg_bones), energy,
                leg_cfg.get("energy_threshold", 0.25), rng
            )
            for i, bone_name in enumerate(leg_bones):
                a = get_or_create(bone_name)
                a.rot[:, 0] += leg_twitches[:, i]

    # ── 6. WEIGHT SHIFT ──────────────────────────────────────────────────
    pelvis_name = skel.get("pelvis")
    if pelvis_name:
        ws = gen_weight_shift(n_frames, fps, breathing, profile)
        # Lateral axis: forward'a dik, up'a dik → sağ-sol
        fwd = cfg["rig"]["axes"].get("forward", "-Z")
        # Basit: Y up, -Z forward → lateral = X
        lateral_idx = 0  # X
        if up_axis == "Z":
            lateral_idx = 1 if "X" in fwd else 0

        a = get_or_create(pelvis_name)
        a.pos[:, lateral_idx] += ws

    return anims


# ═══════════════════════════════════════════════════════════════════════════════
# LOOP SEAL
# ═══════════════════════════════════════════════════════════════════════════════

def apply_loop_seal(anims: Dict[str, BoneAnim], blend_frames: int):
    """Tüm bone'ların rot ve pos verilerini cosine blend ile loop'la."""
    for ba in anims.values():
        ba.rot = cosine_blend_loop(ba.rot, blend_frames)
        ba.pos = cosine_blend_loop(ba.pos, blend_frames)


# ═══════════════════════════════════════════════════════════════════════════════
# BVH EXPORT
# ═══════════════════════════════════════════════════════════════════════════════

def collect_all_bones(skel: Dict) -> List[str]:
    """
    Skeleton config'inden BVH hiyerarşi sırasına göre bone listesi.
    NeedleCrawler hiyerarşisi:
      Hips → tail chain, backleg L, backleg R, chest → head (+ ears), frontleg L, frontleg R
    """
    bones = []
    # pelvis
    bones.append(skel["pelvis"])
    # tail
    for t in skel.get("tail", []):
        bones.append(t)
    # hind legs
    for side in ("left", "right"):
        hl = skel.get("hind_legs", {}).get(side, {})
        for part in ("hip", "upper", "lower", "foot"):
            name = hl.get(part)
            if name:
                bones.append(name)
    # spine (chest)
    for s in skel.get("spine", []):
        bones.append(s)
    # head + ears
    if skel.get("head"):
        bones.append(skel["head"])
    if skel.get("head_end"):
        bones.append(skel["head_end"])
    ears = skel.get("ears", {})
    for side in ("left", "right"):
        if ears.get(side):
            bones.append(ears[side])
    # front legs
    for side in ("left", "right"):
        fl = skel.get("front_legs", {}).get(side, {})
        for part in ("shoulder", "upper", "lower", "foot"):
            name = fl.get(part)
            if name:
                bones.append(name)
    return bones


def build_hierarchy_str(skel: Dict) -> str:
    """BVH HIERARCHY bölümünü metin olarak üret."""
    lines = []
    indent = 0

    def pad():
        return "  " * indent

    def open_joint(keyword, name, offset=(0, 0, 0)):
        nonlocal indent
        lines.append(f"{pad()}{keyword} {name}")
        lines.append(f"{pad()}{{")
        indent += 1
        lines.append(f"{pad()}OFFSET {offset[0]:.4f} {offset[1]:.4f} {offset[2]:.4f}")

    def channels_line(has_pos=False):
        if has_pos:
            lines.append(f"{pad()}CHANNELS 6 Xposition Yposition Zposition Xrotation Yrotation Zrotation")
        else:
            lines.append(f"{pad()}CHANNELS 3 Xrotation Yrotation Zrotation")

    def end_site(offset=(0, 1, 0)):
        nonlocal indent
        lines.append(f"{pad()}End Site")
        lines.append(f"{pad()}{{")
        indent += 1
        lines.append(f"{pad()}OFFSET {offset[0]:.4f} {offset[1]:.4f} {offset[2]:.4f}")
        indent -= 1
        lines.append(f"{pad()}}}")

    def close():
        nonlocal indent
        indent -= 1
        lines.append(f"{pad()}}}")

    def write_chain(names: List[str], is_leaf_chain: bool = True):
        """Lineer kemik zinciri yaz (her biri bir öncekinin child'ı)."""
        for i, name in enumerate(names):
            open_joint("JOINT", name)
            channels_line(has_pos=True)  # her bone'a pos ver (kompanzasyon için)
            if i == len(names) - 1 and is_leaf_chain:
                end_site()

    def close_chain(n: int):
        for _ in range(n):
            close()

    def write_leg(leg_dict: Dict, parts: List[str]):
        """Bacak zincirini yaz."""
        chain = [leg_dict[p] for p in parts if leg_dict.get(p)]
        write_chain(chain, is_leaf_chain=True)
        close_chain(len(chain))

    lines.append("HIERARCHY")

    # ROOT: Hips
    open_joint("ROOT", skel["pelvis"])
    channels_line(has_pos=True)

    # Tail chain
    tail = skel.get("tail", [])
    if tail:
        write_chain(tail)
        close_chain(len(tail))

    # Hind legs
    for side in ("left", "right"):
        hl = skel.get("hind_legs", {}).get(side, {})
        write_leg(hl, ["hip", "upper", "lower", "foot"])

    # Chest (spine)
    spine = skel.get("spine", [])
    for s in spine:
        open_joint("JOINT", s)
        channels_line(has_pos=True)

    # Head
    head = skel.get("head")
    if head:
        open_joint("JOINT", head)
        channels_line(has_pos=True)

        # Head end
        head_end = skel.get("head_end")
        if head_end:
            open_joint("JOINT", head_end)
            channels_line()
            end_site()
            close()

        # Ears
        ears = skel.get("ears", {})
        for side in ("left", "right"):
            ear = ears.get(side)
            if ear:
                open_joint("JOINT", ear)
                channels_line()
                end_site()
                close()

        close()  # head

    # Front legs (chest'in child'ı)
    for side in ("left", "right"):
        fl = skel.get("front_legs", {}).get(side, {})
        write_leg(fl, ["shoulder", "upper", "lower", "foot"])

    # Close spine/chest
    for _ in spine:
        close()

    # Close root
    close()

    return "\n".join(lines)


def build_motion_data(all_bones: List[str], anims: Dict[str, BoneAnim],
                      n_frames: int, root_name: str) -> np.ndarray:
    """
    Her frame için tüm channel değerlerini düz array olarak birleştir.
    Root: 6 channel (pos + rot), diğerleri: config'e bağlı olarak 6 veya 3.
    Basitlik için tüm bone'lara 6 channel (pos + rot) veriyoruz;
    pos animasyonu olmayanlarda sıfır olarak kalır.
    """
    # Hangi bone'ların pos channel'ı var? Hiyerarşi yazarken hepsine verdik
    # (kompanzasyon mekanizması için), headend ve ear'lar hariç (sadece 3 channel).
    # Ama BVH'de tutarlılık için: root ve "has_pos=True" olanlar 6, geri kalan 3.

    # Basit yaklaşım: her bone 6 channel. Karmaşıklığı azalt.
    # NOT: gerçek import'ta Maya/UE fazla channel'ları yoksayar.

    # Aslında hiyerarşi yazarken headend ve ear'lar sadece 3 channel aldı.
    # Bunu eşleştirmemiz lazım.
    bones_with_pos = set()
    bones_with_pos.add(root_name)  # root
    skel = {}  # bu fonksiyonda skel yok, dışarıdan bilmemiz gerekiyor
    # Pragmatik çözüm: anims'te pos verisi olan tüm bone'lar 6 channel,
    # olmayanlar 3.
    # Ama BVH header ile uyuşması lazım. En temizi: hepsine 6 ver header'da.

    # Düzeltme: header'da bazı bone'lara 3 channel verdik. Bunu track etmek yerine
    # hepsini 6 channel yapalım (header'ı da öyle yazalım).
    # Bu Maya import'unda sorun çıkarmaz.

    # Şimdilik: tüm bone'lar 6 channel.
    channels_per_bone = 6
    total_channels = len(all_bones) * channels_per_bone
    motion = np.zeros((n_frames, total_channels))

    for i, bone_name in enumerate(all_bones):
        offset = i * channels_per_bone
        if bone_name in anims:
            ba = anims[bone_name]
            motion[:, offset:offset + 3] = ba.pos    # Xpos, Ypos, Zpos
            motion[:, offset + 3:offset + 6] = ba.rot  # Xrot, Yrot, Zrot

    return motion


def build_hierarchy_str_uniform(skel: Dict) -> Tuple[str, List[str]]:
    """
    Tüm bone'lara 6 channel veren BVH hierarchy.
    İkinci dönüş: bone listesi (traversal sırası, motion data sırası ile aynı).
    """
    lines = []
    bone_order = []
    indent = 0

    def pad():
        return "  " * indent

    def open_joint(keyword, name):
        nonlocal indent
        bone_order.append(name)
        lines.append(f"{pad()}{keyword} {name}")
        lines.append(f"{pad()}{{")
        indent += 1
        lines.append(f"{pad()}OFFSET 0.0000 0.0000 0.0000")
        if keyword == "ROOT":
            lines.append(f"{pad()}CHANNELS 6 Xposition Yposition Zposition Xrotation Yrotation Zrotation")
        else:
            lines.append(f"{pad()}CHANNELS 6 Xposition Yposition Zposition Xrotation Yrotation Zrotation")

    def end_site():
        nonlocal indent
        lines.append(f"{pad()}End Site")
        lines.append(f"{pad()}{{")
        indent += 1
        lines.append(f"{pad()}OFFSET 0.0000 1.0000 0.0000")
        indent -= 1
        lines.append(f"{pad()}}}")

    def close():
        nonlocal indent
        indent -= 1
        lines.append(f"{pad()}}}")

    lines.append("HIERARCHY")

    # ROOT: Hips
    open_joint("ROOT", skel["pelvis"])

    # Tail chain
    tail = skel.get("tail", [])
    for i, t in enumerate(tail):
        open_joint("JOINT", t)
    if tail:
        end_site()
    for _ in tail:
        close()

    # Hind legs
    for side in ("left", "right"):
        hl = skel.get("hind_legs", {}).get(side, {})
        chain = [hl[p] for p in ("hip", "upper", "lower", "foot") if hl.get(p)]
        for c in chain:
            open_joint("JOINT", c)
        if chain:
            end_site()
        for _ in chain:
            close()

    # Spine / Chest
    spine = skel.get("spine", [])
    for s in spine:
        open_joint("JOINT", s)

    # Head
    head = skel.get("head")
    if head:
        open_joint("JOINT", head)

        # Head end
        head_end = skel.get("head_end")
        if head_end:
            open_joint("JOINT", head_end)
            end_site()
            close()

        # Ears
        ears = skel.get("ears", {})
        for side_name in ("left", "right"):
            ear = ears.get(side_name)
            if ear:
                open_joint("JOINT", ear)
                end_site()
                close()

        close()  # head

    # Front legs (chest child)
    for side in ("left", "right"):
        fl = skel.get("front_legs", {}).get(side, {})
        chain = [fl[p] for p in ("shoulder", "upper", "lower", "foot") if fl.get(p)]
        for c in chain:
            open_joint("JOINT", c)
        if chain:
            end_site()
        for _ in chain:
            close()

    # Close spine
    for _ in spine:
        close()

    # Close root
    close()

    return "\n".join(lines), bone_order


def write_bvh(filepath: Path, hierarchy_str: str, bone_order: List[str],
              anims: Dict[str, BoneAnim], n_frames: int, fps: int):
    """BVH dosyasını yaz."""
    # Motion data: bone_order sırasıyla 6 channel per bone
    channels_per_bone = 6
    total_channels = len(bone_order) * channels_per_bone
    motion = np.zeros((n_frames, total_channels))

    for i, bone_name in enumerate(bone_order):
        offset = i * channels_per_bone
        if bone_name in anims:
            ba = anims[bone_name]
            motion[:, offset:offset + 3] = ba.pos
            motion[:, offset + 3:offset + 6] = ba.rot

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(hierarchy_str)
        f.write("\n")
        f.write("MOTION\n")
        f.write(f"Frames: {n_frames}\n")
        f.write(f"Frame Time: {1.0 / fps:.6f}\n")
        for frame_idx in range(n_frames):
            vals = " ".join(f"{v:.4f}" for v in motion[frame_idx])
            f.write(vals + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# PREVIEW
# ═══════════════════════════════════════════════════════════════════════════════

def plot_preview(anims: Dict[str, BoneAnim], cfg: Dict, n_frames: int,
                 fps: int, energy: Optional[np.ndarray], output_path: Path):
    """Üretilen animasyonun kanal bazlı önizlemesi."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[preview] matplotlib yok, atlandı.")
        return

    skel = cfg["rig"]["skeleton"]
    t = np.arange(n_frames) / fps

    fig, axes = plt.subplots(5, 1, figsize=(12, 10), sharex=True)

    # 1. Chest breathing (pos Y)
    chest = skel["spine"][0] if skel.get("spine") else None
    if chest and chest in anims:
        axes[0].plot(t, anims[chest].pos[:, 1], color="#4a90e2", linewidth=1.2)
        axes[0].set_ylabel("Chest Y pos")
        axes[0].set_title("Compose Preview — Procedural Idle")
    axes[0].grid(alpha=0.3)

    # 2. Head yaw
    head = skel.get("head")
    if head and head in anims:
        axes[1].plot(t, anims[head].rot[:, 1], color="#e2794a", linewidth=1.2)
    axes[1].set_ylabel("Head yaw (°)")
    axes[1].grid(alpha=0.3)

    # 3. Tail (first bone yaw)
    tail_bones = skel.get("tail", [])
    colors = ["#2ecc71", "#27ae60", "#1abc9c", "#16a085", "#0e8c6e"]
    for i, tb in enumerate(tail_bones[:3]):
        if tb in anims:
            c = colors[i % len(colors)]
            axes[2].plot(t, anims[tb].rot[:, 1], color=c, linewidth=1, label=tb)
    axes[2].set_ylabel("Tail yaw (°)")
    axes[2].legend(fontsize=7)
    axes[2].grid(alpha=0.3)

    # 4. Ear/Leg twitches
    ear_cfg = cfg["profile"].get("ear_twitch", {})
    ear_bones = ear_cfg.get("candidate_bones", [])
    for eb in ear_bones:
        if eb in anims:
            axes[3].plot(t, anims[eb].rot[:, 0], linewidth=0.8, label=eb)
    leg_cfg = cfg["profile"].get("leg_twitch", {})
    leg_bones = leg_cfg.get("candidate_bones", [])
    for lb in leg_bones[:2]:
        if lb in anims:
            axes[3].plot(t, anims[lb].rot[:, 0], linewidth=0.8, alpha=0.6, label=lb)
    axes[3].set_ylabel("Twitches (°)")
    axes[3].legend(fontsize=6, ncol=3)
    axes[3].grid(alpha=0.3)

    # 5. Energy curve (reference)
    if energy is not None:
        e_res = resample_curve(energy, n_frames)
        axes[4].plot(t, e_res, color="#9b59b6", linewidth=1.2)
        axes[4].set_ylabel("Energy (HY-Motion)")
    else:
        axes[4].text(0.5, 0.5, "No energy curve", transform=axes[4].transAxes,
                     ha="center", va="center", color="gray")
    axes[4].set_xlabel("Zaman (s)")
    axes[4].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=100)
    print(f"[preview] Kaydedildi: {output_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def build_fbx_hierarchy(skel: Dict) -> List[Tuple[str, Optional[str], Tuple[float, float, float]]]:
    """
    FBX writer için (bone_name, parent_name, offset) listesi üret.
    NeedleCrawler hiyerarşisi:
      Hips → tail chain, backleg L, R, chest → head (+ears), frontleg L, R
    """
    hierarchy = []

    pelvis = skel["pelvis"]
    hierarchy.append((pelvis, None, (0.0, 0.0, 0.0)))

    # Tail chain — parent'ı Hips
    tail = skel.get("tail", [])
    prev = pelvis
    for tb in tail:
        hierarchy.append((tb, prev, (0.0, 0.0, -5.0)))  # kuyruk arkaya uzanır
        prev = tb

    # Hind legs (Hips child)
    for side in ("left", "right"):
        hl = skel.get("hind_legs", {}).get(side, {})
        chain = [hl[p] for p in ("hip", "upper", "lower", "foot") if hl.get(p)]
        prev = pelvis
        offset_x = -10.0 if side == "left" else 10.0
        first = True
        for cb in chain:
            offset = (offset_x, -5.0, 0.0) if first else (0.0, -10.0, 0.0)
            hierarchy.append((cb, prev, offset))
            prev = cb
            first = False

    # Spine / Chest
    spine = skel.get("spine", [])
    prev = pelvis
    for s in spine:
        hierarchy.append((s, prev, (0.0, 8.0, 0.0)))
        prev = s
    chest_node = prev  # son spine bone (chest)

    # Head
    head = skel.get("head")
    if head:
        hierarchy.append((head, chest_node, (0.0, 5.0, 5.0)))

        head_end = skel.get("head_end")
        if head_end:
            hierarchy.append((head_end, head, (0.0, 2.0, 3.0)))

        ears = skel.get("ears", {})
        for side_name in ("left", "right"):
            ear = ears.get(side_name)
            if ear:
                offset_x = -2.0 if side_name == "left" else 2.0
                hierarchy.append((ear, head, (offset_x, 2.0, 0.0)))

    # Front legs — chest'in child'ı
    for side in ("left", "right"):
        fl = skel.get("front_legs", {}).get(side, {})
        chain = [fl[p] for p in ("shoulder", "upper", "lower", "foot") if fl.get(p)]
        prev = chest_node if chest_node else pelvis
        offset_x = -8.0 if side == "left" else 8.0
        first = True
        for cb in chain:
            offset = (offset_x, -2.0, 0.0) if first else (0.0, -8.0, 0.0)
            hierarchy.append((cb, prev, offset))
            prev = cb
            first = False

    return hierarchy


def main():
    parser = argparse.ArgumentParser(description="Procedural quadruped idle → BVH/FBX")
    parser.add_argument("--config", type=Path, required=True, help="Rig + profile JSON")
    parser.add_argument("--energy", type=Path, default=None, help="curves.json (energy source)")
    parser.add_argument("--output", type=Path, required=True, help="Çıktı dosyası (.bvh veya .fbx)")
    parser.add_argument("--format", choices=["bvh", "fbx", "auto"], default="auto",
                        help="Çıktı formatı. 'auto' = uzantıdan tahmin eder.")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42, help="Random seed (twitch timing)")
    parser.add_argument("--preview", type=Path, default=None, help="Opsiyonel preview PNG")
    args = parser.parse_args()

    # Format tespiti
    fmt = args.format
    if fmt == "auto":
        ext = args.output.suffix.lower()
        if ext == ".fbx":
            fmt = "fbx"
        elif ext == ".bvh":
            fmt = "bvh"
        else:
            print(f"[hata] Uzantıdan format anlaşılamadı ({ext}). --format kullanın.")
            sys.exit(1)
    print(f"[format] {fmt.upper()}")

    # Load config
    cfg = load_config(args.config)
    profile = cfg["profile"]

    # Energy source
    energy = None
    energy_cfg = profile.get("energy_source", {})
    if args.energy:
        energy = load_energy_curve(args.energy)
        if energy is not None:
            print(f"[energy] Yüklendi: {args.energy} ({len(energy)} frame)")
    elif energy_cfg.get("type") == "hymotion" and energy_cfg.get("curves_json"):
        ep = args.config.parent / energy_cfg["curves_json"]
        energy = load_energy_curve(ep)
        if energy is not None:
            print(f"[energy] Config'ten yüklendi: {ep} ({len(energy)} frame)")

    if energy is None:
        print("[energy] Energy curve yok — twitch'ler energy-independent çalışacak.")

    # Frame sayısı
    loop_cfg = profile.get("loop", {})
    duration_sec = loop_cfg.get("target_duration_sec", 5.0)
    n_frames = int(duration_sec * args.fps)
    print(f"[compose] {n_frames} frame, {duration_sec}s, {args.fps} fps")

    # Build animations
    anims = build_bone_anims(cfg, n_frames, args.fps, energy, seed=args.seed)
    print(f"[compose] {len(anims)} bone animasyonu üretildi")

    # Loop seal
    blend = loop_cfg.get("seamless_blend_frames", 12)
    apply_loop_seal(anims, blend)
    print(f"[loop] {blend} frame cosine blend uygulandı")

    skel = cfg["rig"]["skeleton"]
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # -- Write ---------------------------------------------------------------
    if fmt == "bvh":
        hierarchy_str, bone_order = build_hierarchy_str_uniform(skel)
        print(f"[bvh] {len(bone_order)} bone hiyerarşide")
        write_bvh(args.output, hierarchy_str, bone_order, anims, n_frames, args.fps)
        print(f"[done] BVH kaydedildi: {args.output}")
    else:  # fbx
        from fbx_writer import write_fbx_animation

        fbx_hier = build_fbx_hierarchy(skel)
        print(f"[fbx] {len(fbx_hier)} bone hiyerarşide")

        # anim_data formatı: {bone: {pos: (T,3), rot: (T,3)}}
        anim_data = {}
        for bone_name, ba in anims.items():
            anim_data[bone_name] = {
                "pos": ba.pos,
                "rot": ba.rot,
            }

        write_fbx_animation(
            output_path=str(args.output),
            bone_hierarchy=fbx_hier,
            animation_data=anim_data,
            fps=args.fps,
            n_frames=n_frames,
            anim_stack_name="Idle",
        )
        print(f"[done] FBX kaydedildi: {args.output}")

    # Preview
    if args.preview:
        plot_preview(anims, cfg, n_frames, args.fps, energy, args.preview)


if __name__ == "__main__":
    main()
