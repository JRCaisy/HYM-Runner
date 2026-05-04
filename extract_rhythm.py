"""
extract_rhythm.py
-----------------
HY-Motion 1.0 çıktısından (npz) NeedleCrawler idle için kullanılabilir
zamanlama sinyalleri çıkarır.

Çıktılar:
  - breathing_curve  : pelvis Y'den türetilmiş, nefes benzeri düşük frekanslı sinyal
  - energy_curve     : tüm joint hızlarının RMS'i, genel motion enerjisi
  - loop_candidates  : döngü dikişi için en sakin frame'lerin indeksleri
  - meta             : fps, süre, gövde yönelim bilgileri

HY-Motion npz yapısı (ComfyUI entegrasyonundan teyitli):
  keypoints3d        : (T, 22, 3)   -- joint pozisyonları (SMPL-H)
  transl             : (T, 3)       -- global root translation
  rot6d              : (T, J, 6)    -- joint rotasyonları
  root_rotations_mat : (T, 3, 3)    -- root rotation matrix

SMPL-H joint index'leri (bizim için önemli olanlar):
  0  = pelvis
  3  = spine1
  6  = spine2
  9  = spine3 (chest)
  12 = neck
  15 = head

Kullanım:
  python extract_rhythm.py --input motion.npz --output curves.json
  python extract_rhythm.py --input motion.npz --output curves.json --plot rhythm.png

Bağımlılıklar:
  numpy, scipy (filtre için), opsiyonel: matplotlib (görselleştirme için)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

try:
    from scipy.signal import butter, filtfilt, find_peaks
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False


# -- SMPL-H joint haritası (kullandığımız subset) ------------------------------
JOINT = {
    "pelvis": 0,
    "spine1": 3,
    "spine2": 6,
    "chest":  9,   # spine3
    "neck":   12,
    "head":   15,
    "l_shoulder": 16,
    "r_shoulder": 17,
    "l_hip": 1,
    "r_hip": 2,
}

DEFAULT_FPS = 30  # HY-Motion 30 fps üretir (paper Section 2.1)


# -- Yükleme -------------------------------------------------------------------
def load_motion(npz_path: Path) -> Dict[str, np.ndarray]:
    """HY-Motion npz dosyasını yükler ve minimal doğrulama yapar."""
    if not npz_path.exists():
        raise FileNotFoundError(f"Motion dosyası bulunamadı: {npz_path}")

    data = np.load(npz_path, allow_pickle=True)
    keys = list(data.keys())
    print(f"[load] Mevcut key'ler: {keys}")

    out = {}
    # En kritik iki tane bunlar. Diğerleri varsa al, yoksa sessizce geç.
    for key in ("keypoints3d", "transl", "rot6d", "root_rotations_mat"):
        if key in data:
            out[key] = np.asarray(data[key])
            print(f"[load] {key:22s} shape={out[key].shape} dtype={out[key].dtype}")

    # En azından birini istiyoruz. Yoksa script çalışamaz.
    if "keypoints3d" not in out and "transl" not in out:
        raise ValueError(
            "npz dosyasında ne 'keypoints3d' ne 'transl' var. "
            "Bu bir HY-Motion çıktısı değil gibi görünüyor."
        )

    return out


# -- Sinyal işleme yardımcıları ------------------------------------------------
def lowpass(signal: np.ndarray, fps: int, cutoff_hz: float) -> np.ndarray:
    """
    Zero-phase low-pass filter. scipy yoksa basit bir moving average'a düşer.
    Nefes bandı ~0.2-0.6 Hz olduğu için cutoff'u ~1.5 Hz'de tutmak mantıklı.
    """
    if SCIPY_OK and len(signal) > 15:
        nyq = fps / 2.0
        wn = min(cutoff_hz / nyq, 0.99)
        b, a = butter(N=3, Wn=wn, btype="low")
        # filtfilt uç kısımlarda patlamasın diye sinyal yeterince uzun olmalı
        pad = max(3 * max(len(a), len(b)), 1)
        if len(signal) > pad:
            return filtfilt(b, a, signal)

    # Fallback: basit kutu filtresi
    window = max(3, int(fps / max(cutoff_hz, 0.1) / 2) | 1)  # tek sayı
    kernel = np.ones(window) / window
    return np.convolve(signal, kernel, mode="same")


def normalize(signal: np.ndarray, mode: str = "minmax") -> np.ndarray:
    """Sinyali 0-1 veya -1-1 aralığına ölçekle."""
    s = np.asarray(signal, dtype=np.float64)
    if mode == "minmax":
        lo, hi = s.min(), s.max()
        if hi - lo < 1e-9:
            return np.zeros_like(s)
        return (s - lo) / (hi - lo)
    elif mode == "zeromean":
        s = s - s.mean()
        peak = np.abs(s).max()
        return s / peak if peak > 1e-9 else s
    else:
        raise ValueError(f"Bilinmeyen normalize modu: {mode}")


# -- Curve çıkarımı ------------------------------------------------------------
def extract_breathing_curve(
    motion: Dict[str, np.ndarray],
    fps: int,
    cutoff_hz: float = 1.5,
) -> np.ndarray:
    """
    Nefes curve'ü için en iyi kaynak: göğüs (chest) joint'inin dikey hareketi,
    pelvis'in dikey hareketiyle relative olarak alındığında. Çünkü pelvis Y
    root translation'la karışabilir ve drift içerebilir; chest - pelvis farkı
    gerçek "gövde yukarı-aşağı" sinyalini verir.

    Fallback: sadece pelvis/transl Y'si.
    """
    if "keypoints3d" in motion and motion["keypoints3d"].shape[1] > JOINT["chest"]:
        kp = motion["keypoints3d"]  # (T, 22, 3)
        # Y ekseninin hangisi olduğu convention'a bağlı. HY-Motion paper
        # "Y-axis up" diyor (Section 2.1 canonicalization). Yani axis=1.
        chest_y  = kp[:, JOINT["chest"],  1]
        pelvis_y = kp[:, JOINT["pelvis"], 1]
        raw = chest_y - pelvis_y
        source = "chest - pelvis (Y)"
    elif "transl" in motion:
        raw = motion["transl"][:, 1]
        source = "transl Y (fallback)"
    else:
        raise ValueError("Nefes curve'ü için uygun veri yok.")

    print(f"[breathing] kaynak: {source}, ham aralık: "
          f"{raw.min():.4f} → {raw.max():.4f} (metre)")

    # Düşük geçiren filtre: yürüyüş gibi yüksek frekansları kes, nefesi bırak
    smooth = lowpass(raw, fps=fps, cutoff_hz=cutoff_hz)

    # Zero-mean, -1..1'e normalize — composer tarafında amplitude
    # NeedleCrawler rig'inin kendi parametresiyle çarpılacak
    return normalize(smooth, mode="zeromean")


def extract_energy_curve(
    motion: Dict[str, np.ndarray],
    fps: int,
    smooth_hz: float = 2.0,
) -> np.ndarray:
    """
    Genel motion enerjisi: tüm joint'lerin frame-to-frame hızının RMS'i.
    Düşük energy = sakin an (loop dikişi için ideal).
    Yüksek energy = hareket (twitch timing'i için referans).

    Sadece transl varsa tek boyutlu hız.
    """
    if "keypoints3d" in motion:
        kp = motion["keypoints3d"]  # (T, J, 3)
        # Joint hızları: frame farkı
        vel = np.diff(kp, axis=0)                   # (T-1, J, 3)
        speed = np.linalg.norm(vel, axis=2)          # (T-1, J)
        energy = np.sqrt((speed ** 2).mean(axis=1))  # (T-1,)
        # İlk frame'e pad ederek uzunluğu eşitle
        energy = np.concatenate([[energy[0]], energy])
    elif "transl" in motion:
        t = motion["transl"]
        vel = np.diff(t, axis=0)
        speed = np.linalg.norm(vel, axis=1)
        energy = np.concatenate([[speed[0]], speed])
    else:
        raise ValueError("Energy curve'ü için uygun veri yok.")

    # Yumuşat — tek frame'lik spike'lar loop detection'ı bozmasın
    smooth = lowpass(energy, fps=fps, cutoff_hz=smooth_hz)
    return normalize(smooth, mode="minmax")


def find_loop_candidates(
    energy: np.ndarray,
    fps: int,
    top_n: int = 5,
    margin_sec: float = 0.5,
) -> list:
    """
    En sakin frame'leri bul. Loop dikişi için sinyalin düşük olduğu
    ve iki kenarda (başta/sonda) olmayan noktalar tercih edilir.
    """
    margin = int(margin_sec * fps)
    if len(energy) < 2 * margin + 3:
        # Çok kısa motion, orta nokta dön
        return [len(energy) // 2]

    # Uçları maskele
    searchable = energy.copy()
    searchable[:margin] = 1.0
    searchable[-margin:] = 1.0

    # Düşük energy = yüksek "durgunluk". -searchable ile peak'leri bul.
    if SCIPY_OK:
        peaks, _ = find_peaks(-searchable, distance=int(fps * 0.3))
        if len(peaks) == 0:
            # Peak bulamadıysa manuel argmin
            return [int(np.argmin(searchable))]
        # Energy değerine göre sırala (en sakin önce)
        peaks_sorted = sorted(peaks, key=lambda i: searchable[i])
        return [int(p) for p in peaks_sorted[:top_n]]

    # scipy yoksa basit yaklaşım: en düşük N nokta (min-distance kontrollü)
    idx_sorted = np.argsort(searchable)
    picked = []
    min_dist = int(fps * 0.3)
    for i in idx_sorted:
        if all(abs(int(i) - p) >= min_dist for p in picked):
            picked.append(int(i))
        if len(picked) >= top_n:
            break
    return picked


# -- Orkestrasyon --------------------------------------------------------------
def extract_rhythm(npz_path: Path, fps: int = DEFAULT_FPS) -> Dict:
    """Ana pipeline: yükle → curve'leri çıkar → metadata ile paketle."""
    motion = load_motion(npz_path)

    # Frame sayısını bul (hangi key varsa)
    if "keypoints3d" in motion:
        n_frames = motion["keypoints3d"].shape[0]
    else:
        n_frames = motion["transl"].shape[0]

    breathing = extract_breathing_curve(motion, fps=fps)
    energy = extract_energy_curve(motion, fps=fps)
    loop_candidates = find_loop_candidates(energy, fps=fps)

    print(f"[summary] frames={n_frames}, süre={n_frames/fps:.2f}s, "
          f"loop adayları (frame)={loop_candidates}")

    return {
        "meta": {
            "source_file": str(npz_path.name),
            "fps": fps,
            "n_frames": int(n_frames),
            "duration_sec": round(n_frames / fps, 3),
            "scipy_available": SCIPY_OK,
        },
        "breathing_curve": breathing.tolist(),
        "energy_curve": energy.tolist(),
        "loop_candidates": loop_candidates,
    }


# -- Görselleştirme (opsiyonel) ------------------------------------------------
def plot_curves(result: Dict, output_path: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[plot] matplotlib yok, görselleştirme atlandı.")
        return

    fps = result["meta"]["fps"]
    breathing = np.array(result["breathing_curve"])
    energy = np.array(result["energy_curve"])
    t = np.arange(len(breathing)) / fps

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    ax1.plot(t, breathing, color="#4a90e2", linewidth=1.5)
    ax1.axhline(0, color="gray", linewidth=0.5, alpha=0.5)
    ax1.set_ylabel("Breathing (normalized)")
    ax1.set_title(f"Rhythm Extraction — {result['meta']['source_file']}")
    ax1.grid(alpha=0.3)

    ax2.plot(t, energy, color="#e27c4a", linewidth=1.5)
    for lc in result["loop_candidates"]:
        ax2.axvline(lc / fps, color="green", linewidth=0.8, alpha=0.5,
                    linestyle="--")
    ax2.set_ylabel("Motion energy")
    ax2.set_xlabel("Zaman (s)")
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=100)
    print(f"[plot] Kaydedildi: {output_path}")


# -- CLI -----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="HY-Motion npz'den NeedleCrawler için ritim sinyali çıkar."
    )
    parser.add_argument("--input", type=Path, required=True,
                        help="HY-Motion çıktı .npz dosyası")
    parser.add_argument("--output", type=Path, required=True,
                        help="Çıktı JSON dosyası")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS,
                        help=f"Frame rate (default: {DEFAULT_FPS})")
    parser.add_argument("--plot", type=Path, default=None,
                        help="Opsiyonel: curve görseli için PNG yolu")
    args = parser.parse_args()

    try:
        result = extract_rhythm(args.input, fps=args.fps)
    except Exception as e:
        print(f"[hata] {e}", file=sys.stderr)
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"[done] JSON kaydedildi: {args.output}")

    if args.plot:
        plot_curves(result, args.plot)


if __name__ == "__main__":
    main()
