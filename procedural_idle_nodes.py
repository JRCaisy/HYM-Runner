"""
procedural_idle_nodes.py
------------------------
ComfyUI node'ları — NeedleCrawler Procedural Idle Pipeline

Üç node:
  1. ExtractRhythm   — HY-Motion npz → curves.json
  2. ComposeIdle     — curves.json + config → FBX
  3. LoadRigConfig   — JSON config dosyası seçici (helper)

Kurulum:
  Bu dosyayı ComfyUI/custom_nodes/hy_motion_idle/ klasörüne koy.
  Yanına şunları da koy (aynı klasöre):
    extract_rhythm.py
    compose_idle.py
    fbx_writer.py
    validate_config.py
    configs/needlecrawler.json
    configs/curves_v08.json     (energy source)

ComfyUI workflow örneği:
  [HY-Motion Runner] → npz_path
          │
          ▼
  [Extract Rhythm]  → curves_json_path
          │
          ▼
  [Compose Idle] ← [Load Rig Config] → rig_config_path
          │
          ▼
        fbx_path
"""

import os
import sys
import json
from pathlib import Path

# Bu dosyanın bulunduğu klasörü Python path'e ekle
# (extract_rhythm, compose_idle, fbx_writer buradan import edilecek)
NODE_DIR = Path(__file__).resolve().parent
if str(NODE_DIR) not in sys.path:
    sys.path.insert(0, str(NODE_DIR))


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 1 — ExtractRhythm
# ═══════════════════════════════════════════════════════════════════════════════

class ExtractRhythm:
    """
    HY-Motion npz çıktısından energy + breathing curve çıkarır.
    HY-Motion Runner'ın npz_path çıktısını direkt alır.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "npz_path": ("STRING", {
                    "default": "",
                    "tooltip": "HY-Motion Runner'dan gelen npz dosya yolu"
                }),
                "output_dir": ("STRING", {
                    "default": "",
                    "tooltip": "curves.json'un kaydedileceği klasör. Boş = npz ile aynı klasör."
                }),
                "output_name": ("STRING", {
                    "default": "curves",
                    "tooltip": "Çıktı dosya adı (uzantısız). Örn: curves_v08"
                }),
                "save_plot": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "rhythm_<name>.png görsel çıktısını kaydet"
                }),
            },
            "optional": {
                "fps": ("INT", {
                    "default": 30,
                    "min": 24,
                    "max": 60,
                    "step": 1,
                    "tooltip": "HY-Motion 30 fps üretir, değiştirme."
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("curves_json_path", "plot_path")
    FUNCTION = "execute"
    CATEGORY = "HYMotion/Quadruped Idle"
    OUTPUT_NODE = True

    def execute(self, npz_path: str, output_dir: str, output_name: str,
                save_plot: bool, fps: int = 30):

        npz_path = npz_path.strip()
        if not npz_path or not Path(npz_path).exists():
            raise ValueError(f"[ExtractRhythm] npz dosyası bulunamadı: '{npz_path}'")

        npz = Path(npz_path)

        # Çıktı klasörü
        if output_dir.strip():
            out_dir = Path(output_dir.strip())
        else:
            out_dir = npz.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        curves_path = out_dir / f"{output_name}.json"
        plot_path = out_dir / f"rhythm_{output_name}.png" if save_plot else None

        # extract_rhythm import
        try:
            from extract_rhythm import extract_rhythm, plot_curves
        except ImportError as e:
            raise ImportError(
                f"[ExtractRhythm] extract_rhythm.py import edilemedi: {e}\n"
                f"NODE_DIR={NODE_DIR}"
            )

        result = extract_rhythm(npz, fps=fps)

        with open(curves_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        plot_out = ""
        if save_plot and plot_path:
            try:
                plot_curves(result, plot_path)
                plot_out = str(plot_path)
            except Exception as e:
                print(f"[ExtractRhythm] Plot oluşturulamadı: {e}")

        print(f"[ExtractRhythm] curves.json → {curves_path}")
        n_frames = result["meta"]["n_frames"]
        duration = result["meta"]["duration_sec"]
        fmt = result["meta"]["source_format"]
        print(f"[ExtractRhythm] {n_frames} frame, {duration}s, format={fmt}")

        return (str(curves_path), plot_out)


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 2 — LoadRigConfig  (helper)
# ═══════════════════════════════════════════════════════════════════════════════

class LoadRigConfig:
    """
    Rig config JSON dosyasını seçer ve path'ini döndürür.
    Compose Idle node'una bağlanır.
    """

    @classmethod
    def INPUT_TYPES(cls):
        # configs/ klasöründeki JSON'ları listele
        configs_dir = NODE_DIR / "configs"
        json_files = []
        if configs_dir.exists():
            json_files = [f.name for f in configs_dir.glob("*.json")
                          if not f.name.startswith("quadruped_schema")]
        if not json_files:
            json_files = ["needlecrawler.json"]

        return {
            "required": {
                "config_file": (json_files, {
                    "default": json_files[0] if json_files else "needlecrawler.json",
                    "tooltip": "configs/ klasöründeki rig config dosyası"
                }),
            },
            "optional": {
                "custom_config_path": ("STRING", {
                    "default": "",
                    "tooltip": "Özel bir config yolu belirtmek istersen buraya yaz (config_file'ı geçersiz kılar)"
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("rig_config_path",)
    FUNCTION = "execute"
    CATEGORY = "HYMotion/Quadruped Idle"

    def execute(self, config_file: str, custom_config_path: str = ""):
        if custom_config_path.strip():
            config_path = Path(custom_config_path.strip())
        else:
            config_path = NODE_DIR / "configs" / config_file

        if not config_path.exists():
            raise ValueError(f"[LoadRigConfig] Config bulunamadı: {config_path}")

        print(f"[LoadRigConfig] Config yüklendi: {config_path}")
        return (str(config_path),)


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 3 — ComposeIdle
# ═══════════════════════════════════════════════════════════════════════════════

class ComposeIdle:
    """
    curves.json + rig config → FBX idle animasyonu üretir.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "rig_config_path": ("STRING", {
                    "default": "",
                    "tooltip": "LoadRigConfig node'undan veya manuel yol"
                }),
                "output_path": ("STRING", {
                    "default": "idle_output.fbx",
                    "tooltip": "Çıktı FBX dosyasının tam yolu. .fbx veya .bvh uzantısı."
                }),
                "seed": ("INT", {
                    "default": 42,
                    "min": 0,
                    "max": 9999999,
                    "step": 1,
                    "tooltip": "Twitch event timing için random seed. Farklı seed farklı seğirme pattern'i üretir."
                }),
                "fps": ("INT", {
                    "default": 30,
                    "min": 24,
                    "max": 60,
                    "step": 1,
                }),
                "save_preview": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "idle_preview.png kanal bazlı önizleme kaydet"
                }),
            },
            "optional": {
                "curves_json_path": ("STRING", {
                    "default": "",
                    "tooltip": "ExtractRhythm'den gelen curves.json yolu. "
                               "Boş = config'teki energy_source.curves_json kullanılır."
                }),
                "duration_sec_override": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 30.0,
                    "step": 0.5,
                    "tooltip": "0 = config'teki süreyi kullan. Pozitif değer config'i override eder."
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("fbx_path",)
    FUNCTION = "execute"
    CATEGORY = "HYMotion/Quadruped Idle"
    OUTPUT_NODE = True

    def execute(self, rig_config_path: str, output_path: str, seed: int,
                fps: int, save_preview: bool,
                curves_json_path: str = "", duration_sec_override: float = 0.0):

        rig_config_path = rig_config_path.strip()
        output_path = output_path.strip()

        if not rig_config_path or not Path(rig_config_path).exists():
            raise ValueError(f"[ComposeIdle] Config bulunamadı: '{rig_config_path}'")

        try:
            from compose_idle import (
                load_config, load_energy_curve,
                build_bone_anims, apply_loop_seal,
                build_hierarchy_str_uniform, write_bvh,
                build_fbx_hierarchy, plot_preview
            )
            from fbx_writer import write_fbx_animation
        except ImportError as e:
            raise ImportError(
                f"[ComposeIdle] Gerekli modül import edilemedi: {e}\n"
                f"NODE_DIR={NODE_DIR}\n"
                "compose_idle.py ve fbx_writer.py node klasöründe olmalı."
            )

        # Config yükle
        cfg = load_config(Path(rig_config_path))
        profile = cfg["profile"]

        # Energy source
        energy = None
        if curves_json_path.strip():
            energy = load_energy_curve(Path(curves_json_path.strip()))
            if energy is not None:
                print(f"[ComposeIdle] Energy: {curves_json_path} ({len(energy)} frame)")
        if energy is None:
            energy_cfg = profile.get("energy_source", {})
            if energy_cfg.get("type") == "hymotion" and energy_cfg.get("curves_json"):
                ep = Path(rig_config_path).parent / energy_cfg["curves_json"]
                energy = load_energy_curve(ep)
                if energy is not None:
                    print(f"[ComposeIdle] Energy (config'ten): {ep}")
        if energy is None:
            print("[ComposeIdle] Energy curve yok — twitch'ler energy-independent.")

        # Frame sayısı
        loop_cfg = profile.get("loop", {})
        if duration_sec_override and duration_sec_override > 0:
            duration_sec = duration_sec_override
        else:
            duration_sec = loop_cfg.get("target_duration_sec", 5.0)
        n_frames = int(duration_sec * fps)
        print(f"[ComposeIdle] {n_frames} frame, {duration_sec}s, {fps} fps, seed={seed}")

        # Animasyon üret
        anims = build_bone_anims(cfg, n_frames, fps, energy, seed=seed)

        # Loop seal
        blend = loop_cfg.get("seamless_blend_frames", 12)
        apply_loop_seal(anims, blend)

        # Output path hazırla
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Format tespiti
        ext = out_path.suffix.lower()
        if ext == ".fbx":
            skel = cfg["rig"]["skeleton"]
            fbx_hier = build_fbx_hierarchy(skel)
            anim_data = {bn: {"pos": ba.pos, "rot": ba.rot} for bn, ba in anims.items()}
            write_fbx_animation(
                output_path=str(out_path),
                bone_hierarchy=fbx_hier,
                animation_data=anim_data,
                fps=fps,
                n_frames=n_frames,
                anim_stack_name="Idle",
            )
            print(f"[ComposeIdle] FBX → {out_path}")
        elif ext == ".bvh":
            skel = cfg["rig"]["skeleton"]
            hierarchy_str, bone_order = build_hierarchy_str_uniform(skel)
            write_bvh(out_path, hierarchy_str, bone_order, anims, n_frames, fps)
            print(f"[ComposeIdle] BVH → {out_path}")
        else:
            raise ValueError(f"[ComposeIdle] Bilinmeyen format: {ext}. .fbx veya .bvh kullan.")

        # Preview
        if save_preview:
            preview_path = out_path.with_name(out_path.stem + "_preview.png")
            try:
                plot_preview(anims, cfg, n_frames, fps, energy, preview_path)
            except Exception as e:
                print(f"[ComposeIdle] Preview oluşturulamadı: {e}")

        return (str(out_path),)


# ═══════════════════════════════════════════════════════════════════════════════
# COMFYUI MAPPINGS
# ═══════════════════════════════════════════════════════════════════════════════

NODE_CLASS_MAPPINGS = {
    "ExtractRhythm":  ExtractRhythm,
    "LoadRigConfig":  LoadRigConfig,
    "ComposeIdle":    ComposeIdle,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ExtractRhythm": "Extract Rhythm (HY-Motion → Curves)",
    "LoadRigConfig": "Load Rig Config",
    "ComposeIdle":   "Compose Quadruped Idle → FBX",
}
