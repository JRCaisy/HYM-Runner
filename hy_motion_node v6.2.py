import os
import re
import json
import uuid
import shutil
import random
import subprocess
from pathlib import Path


NODE_DIR = Path(__file__).resolve().parent
PRESET_LIBRARY_PATH = NODE_DIR / "preset_library.json"


DEFAULT_PRESETS = {
    "idle": "A person stands still breathing slowly.",
    "walk": "A person walks forward naturally.",
    "run": "A person runs forward naturally.",
    "jog": "A person jogs forward with relaxed arms.",
    "jump": "A person jumps upward with both legs once.",
    "double_jump": "A person jumps upward with both legs twice.",
    "turn_left": "A person turns left naturally in place.",
    "turn_right": "A person turns right naturally in place.",
    "wave": "A person waves one hand while standing.",
    "salute": "A person gives a soldier salute.",
    "attack_light": "A person performs a quick light melee attack.",
    "attack_heavy": "A person performs a heavy melee attack with full body motion.",
    "hit_react": "A person reacts to getting hit and steps back slightly.",
    "death": "A person collapses to the ground dramatically.",
    "crouch_idle": "A person stays in a crouched idle stance.",
    "crouch_walk": "A person walks forward while crouching."
}


def ensure_preset_library():
    if not PRESET_LIBRARY_PATH.exists():
        with open(PRESET_LIBRARY_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PRESETS, f, ensure_ascii=False, indent=2)


def load_presets():
    ensure_preset_library()
    try:
        with open(PRESET_LIBRARY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cleaned = {}
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, str):
                    cleaned[k] = v
            if cleaned:
                return cleaned
    except Exception:
        pass
    return DEFAULT_PRESETS.copy()


def sanitize_name(text: str, max_len: int = 80) -> str:
    text = str(text).strip()
    text = re.sub(r'[<>:"/\\\\|?*]+', "", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = "motion"
    return text[:max_len]


def apply_counter_pattern(text: str, index: int, padding_default: int = 3) -> str:
    if not text:
        return ""

    def repl(match):
        width = len(match.group(0))
        width = max(width, padding_default)
        return str(index).zfill(width)

    return re.sub(r"#+", repl, text)


def has_counter_placeholder(text: str) -> bool:
    return "#" in text if text else False


def extract_numbers(text: str):
    return [int(x) for x in re.findall(r"(\d+)", text)]


def open_folder_in_explorer(folder: Path):
    try:
        os.startfile(str(folder))
    except Exception:
        pass


def summarize_warnings(stdout: str, stderr: str) -> list[str]:
    warnings = []
    joined = f"{stdout}\n{stderr}".lower()

    if "failed to generate static html content" in joined or "no smpl data found" in joined:
        warnings.append("Static HTML preview generation failed, but FBX export may still have succeeded.")

    if "traceback" in joined and "no smpl data found" not in joined:
        warnings.append("One or more runtime tracebacks were detected. Check the log file for details.")

    return warnings


def format_log_block(title: str, content: str) -> str:
    line = "=" * 90
    content = content.strip() if content else "(empty)"
    return f"{line}\n{title}\n{line}\n{content}\n"


class HYMotionRunner:
    @classmethod
    def INPUT_TYPES(cls):
        presets = load_presets()
        preset_names = ["none"] + sorted(list(presets.keys()))

        return {
            "required": {
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "fast athletic style jump ahead with strong landing"
                    },
                ),
                "preset": (
                    preset_names,
                    {
                        "default": "none"
                    },
                ),
                "reload_preset_library": (
                    "BOOLEAN",
                    {
                        "default": False
                    },
                ),
                "model_variant": (
                    ["HY-Motion-1.0-Lite", "HY-Motion-1.0"],
                    {
                        "default": "HY-Motion-1.0-Lite"
                    },
                ),
                "category": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "Locomotion"
                    },
                ),
                "base_name": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "Jump"
                    },
                ),
                "prefix": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": ""
                    },
                ),
                "suffix": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "_###"
                    },
                ),
                "start_index": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 999999,
                        "step": 1
                    },
                ),
                "padding": (
                    "INT",
                    {
                        "default": 3,
                        "min": 1,
                        "max": 8,
                        "step": 1
                    },
                ),
                "duration_frames": (
                    "INT",
                    {
                        "default": 100,
                        "min": 30,
                        "max": 600,
                        "step": 1
                    },
                ),
                "seed_mode": (
                    ["random", "fixed"],
                    {
                        "default": "random"
                    },
                ),
                "num_seeds": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 8,
                        "step": 1
                    },
                ),
                "fixed_seed": (
                    "INT",
                    {
                        "default": 123,
                        "min": 0,
                        "max": 999999999,
                        "step": 1
                    },
                ),
                "overwrite_mode": (
                    ["next", "overwrite", "skip"],
                    {
                        "default": "next"
                    },
                ),
                "flatten_fbx": (
                    "BOOLEAN",
                    {
                        "default": True
                    },
                ),
                "export_npz": (
                    "BOOLEAN",
                    {
                        "default": True
                    },
                ),
                "export_txt": (
                    "BOOLEAN",
                    {
                        "default": False
                    },
                ),
                "export_extra_json": (
                    "BOOLEAN",
                    {
                        "default": False
                    },
                ),
                "cleanup_temp": (
                    "BOOLEAN",
                    {
                        "default": True
                    },
                ),
                "open_output_folder": (
                    "BOOLEAN",
                    {
                        "default": False
                    },
                ),
                "disable_rewrite": (
                    "BOOLEAN",
                    {
                        "default": True
                    },
                ),
                "disable_duration_est": (
                    "BOOLEAN",
                    {
                        "default": True
                    },
                ),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("status", "fbx_path", "output_folder", "log", "npz_path")
    FUNCTION = "run_hy_motion"
    CATEGORY = "HY-Motion"
    OUTPUT_NODE = True

    def _find_files_recursive(self, root: Path, patterns):
        found = []
        if not root.exists():
            return found
        for pattern in patterns:
            found.extend(root.rglob(pattern))
        return sorted(set(found))

    def _build_effective_prompt(self, prompt: str, preset: str, presets: dict) -> str:
        user_prompt = prompt.strip()
        preset_prompt = presets.get(preset)

        if preset == "none":
            return user_prompt

        if not user_prompt:
            return preset_prompt or ""

        return f"{preset_prompt} {user_prompt}".strip()

    def _find_next_index(self, category_dir: Path, start_index: int) -> int:
        if not category_dir.exists():
            return start_index

        found_numbers = []
        for p in category_dir.glob("*.fbx"):
            found_numbers.extend(extract_numbers(p.stem))

        if not found_numbers:
            return start_index

        return max(max(found_numbers) + 1, start_index)

    def _compose_name(
        self,
        category_dir: Path,
        base_name: str,
        prefix: str,
        suffix: str,
        start_index: int,
        padding: int,
        overwrite_mode: str,
    ) -> tuple[str, int | None]:
        safe_base = sanitize_name(base_name, max_len=50)
        prefix = prefix.strip()
        suffix = suffix.strip()

        uses_counter = has_counter_placeholder(prefix) or has_counter_placeholder(suffix)

        if not uses_counter:
            final_name = sanitize_name(f"{prefix}{safe_base}{suffix}", max_len=120)
            return final_name, None

        idx = self._find_next_index(category_dir, start_index)

        if overwrite_mode == "overwrite":
            idx = start_index

        prefix_applied = apply_counter_pattern(prefix, idx, padding)
        suffix_applied = apply_counter_pattern(suffix, idx, padding)
        final_name = sanitize_name(f"{prefix_applied}{safe_base}{suffix_applied}", max_len=120)
        return final_name, idx

    def _write_meta(
        self,
        meta_path: Path,
        *,
        prompt: str,
        effective_prompt: str,
        preset: str,
        model_variant: str,
        category: str,
        base_name: str,
        prefix: str,
        suffix: str,
        final_name: str,
        duration_frames: int,
        seed_mode: str,
        num_seeds: int,
        fixed_seed: int,
        overwrite_mode: str,
        final_fbx_path: Path | None,
        final_npz_path: Path | None,
        final_txt_path: Path | None,
        final_extra_json_paths: list[str],
        command: list[str],
        return_code: int,
        warnings: list[str],
    ):
        meta = {
            "prompt": prompt,
            "effective_prompt": effective_prompt,
            "preset": preset,
            "model_variant": model_variant,
            "category": category,
            "base_name": base_name,
            "prefix": prefix,
            "suffix": suffix,
            "final_name": final_name,
            "duration_frames": duration_frames,
            "seed_mode": seed_mode,
            "num_seeds": num_seeds,
            "fixed_seed": fixed_seed,
            "overwrite_mode": overwrite_mode,
            "final_fbx_path": str(final_fbx_path) if final_fbx_path else None,
            "final_npz_path": str(final_npz_path) if final_npz_path else None,
            "final_txt_path": str(final_txt_path) if final_txt_path else None,
            "final_extra_json_paths": final_extra_json_paths,
            "command": command,
            "return_code": return_code,
            "warnings": warnings,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _write_log(
        self,
        log_path: Path,
        *,
        final_name: str,
        category: str,
        prompt: str,
        effective_prompt: str,
        preset: str,
        model_variant: str,
        duration_frames: int,
        seed_mode: str,
        num_seeds: int,
        fixed_seed: int,
        overwrite_mode: str,
        command: list[str],
        return_code: int,
        stdout: str,
        stderr: str,
        warnings: list[str],
    ):
        header = (
            format_log_block(
                "RUN SUMMARY",
                "\n".join([
                    f"Final Name      : {final_name}",
                    f"Category        : {category}",
                    f"Preset          : {preset}",
                    f"Model Variant   : {model_variant}",
                    f"Duration Frames : {duration_frames}",
                    f"Seed Mode       : {seed_mode}",
                    f"Num Seeds       : {num_seeds}",
                    f"Fixed Seed      : {fixed_seed}",
                    f"Overwrite Mode  : {overwrite_mode}",
                ])
            )
            + format_log_block("PROMPT", prompt)
            + format_log_block("EFFECTIVE PROMPT", effective_prompt)
            + format_log_block("COMMAND", " ".join(command))
            + format_log_block("RETURN CODE", str(return_code))
            + format_log_block("WARNINGS", "\n".join(warnings) if warnings else "(none)")
            + format_log_block("STDOUT", stdout)
            + format_log_block("STDERR", stderr)
        )

        with open(log_path, "w", encoding="utf-8") as f:
            f.write(header)

    def run_hy_motion(
        self,
        prompt: str,
        preset: str,
        reload_preset_library: bool,
        model_variant: str,
        category: str,
        base_name: str,
        prefix: str,
        suffix: str,
        start_index: int,
        padding: int,
        duration_frames: int,
        seed_mode: str,
        num_seeds: int,
        fixed_seed: int,
        overwrite_mode: str,
        flatten_fbx: bool,
        export_npz: bool,
        export_txt: bool,
        export_extra_json: bool,
        cleanup_temp: bool,
        open_output_folder: bool,
        disable_rewrite: bool,
        disable_duration_est: bool,
    ):
        presets = load_presets() if reload_preset_library else load_presets()

        hy_root = Path(r"E:\AI\HY-Motion-1.0")
        python_exe = hy_root / "venv" / "Scripts" / "python.exe"
        infer_script = hy_root / "local_infer.py"
        model_path = hy_root / "ckpts" / "tencent" / model_variant

        final_output_root = Path(r"E:\GRapHiC\Animations\HYM")
        final_output_root.mkdir(parents=True, exist_ok=True)

        if not hy_root.exists():
            return (f"ERROR: HY-Motion root not found: {hy_root}", "", "", "", "")
        if not python_exe.exists():
            return (f"ERROR: HY-Motion python not found: {python_exe}", "", "", "", "")
        if not infer_script.exists():
            return (f"ERROR: local_infer.py not found: {infer_script}", "", "", "", "")
        if not model_path.exists():
            return (f"ERROR: model path not found: {model_path}", "", "", "", "")

        effective_prompt = self._build_effective_prompt(prompt, preset, presets)
        if not effective_prompt:
            return ("ERROR: Prompt is empty.", "", "", "", "")

        safe_category = sanitize_name(category, max_len=50)
        safe_base = sanitize_name(base_name, max_len=50)

        category_dir = final_output_root / safe_category
        category_dir.mkdir(parents=True, exist_ok=True)

        final_name, used_index = self._compose_name(
            category_dir=category_dir,
            base_name=safe_base,
            prefix=prefix,
            suffix=suffix,
            start_index=start_index,
            padding=padding,
            overwrite_mode=overwrite_mode,
        )

        final_fbx_path = category_dir / f"{final_name}.fbx"
        final_npz_path = category_dir / f"{final_name}.npz"
        final_txt_path = category_dir / f"{final_name}.txt"
        final_log_path = category_dir / f"{final_name}.log.txt"
        final_meta_path = category_dir / f"{final_name}.meta.json"

        if overwrite_mode == "skip" and final_fbx_path.exists():
            log = f"SKIPPED: File already exists.\n{final_fbx_path}"
            npz_existing = str(final_npz_path) if final_npz_path.exists() else ""
            return ("SKIPPED", str(final_fbx_path), str(category_dir), log, npz_existing)

        unique_temp_id = uuid.uuid4().hex[:6]

        input_dir = hy_root / "examples" / "example_prompts" / f"comfyui_{final_name}_{unique_temp_id}"
        input_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "test": [
                f"{effective_prompt}#{duration_frames}"
            ]
        }

        input_json_path = input_dir / f"{final_name}.json"
        with open(input_json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        run_output_dir = final_output_root / f"_temp_{final_name}_{unique_temp_id}"
        run_output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(python_exe),
            str(infer_script),
            "--model_path", str(model_path),
            "--input_text_dir", str(input_dir),
            "--output_dir", str(run_output_dir),
            "--num_seeds", str(num_seeds),
        ]

        if disable_rewrite:
            cmd.append("--disable_rewrite")

        if disable_duration_est:
            cmd.append("--disable_duration_est")

        env = os.environ.copy()
        if seed_mode == "fixed":
            env["PYTHONHASHSEED"] = str(fixed_seed)
            random.seed(fixed_seed)

        try:
            result = subprocess.run(
                cmd,
                cwd=str(hy_root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            warnings = summarize_warnings(stdout, stderr)

            fbx_files = self._find_files_recursive(run_output_dir, ["*.fbx", "*.FBX"])
            npz_files = self._find_files_recursive(run_output_dir, ["*.npz", "*.NPZ"])
            txt_files = self._find_files_recursive(run_output_dir, ["*.txt"])
            json_files = self._find_files_recursive(run_output_dir, ["*.json"])
            bvh_files = self._find_files_recursive(run_output_dir, ["*.bvh", "*.BVH"])

            if result.returncode != 0:
                error_log = (
                    format_log_block("COMMAND", " ".join(cmd))
                    + format_log_block("RETURN CODE", str(result.returncode))
                    + format_log_block("STDOUT", stdout)
                    + format_log_block("STDERR", stderr)
                )
                return (
                    "ERROR: local_infer.py failed",
                    "",
                    str(run_output_dir),
                    error_log,
                    "",
                )

            if not fbx_files:
                extras = []
                if npz_files:
                    extras.append(f"NPZ found: {npz_files[0]}")
                if bvh_files:
                    extras.append(f"BVH found: {bvh_files[0]}")
                if json_files:
                    extras.append(f"JSON found: {json_files[0]}")
                if txt_files:
                    extras.append(f"TXT found: {txt_files[0]}")
                if not extras:
                    extras.append("No FBX/NPZ/BVH/JSON/TXT output found.")

                error_log = (
                    format_log_block("COMMAND", " ".join(cmd))
                    + format_log_block("RETURN CODE", str(result.returncode))
                    + format_log_block("WARNINGS", "\n".join(warnings) if warnings else "(none)")
                    + format_log_block("STDOUT", stdout)
                    + format_log_block("STDERR", stderr)
                )

                return (
                    "ERROR: Inference finished but no FBX was generated. " + " | ".join(extras),
                    "",
                    str(run_output_dir),
                    error_log,
                    "",
                )

            first_fbx = fbx_files[0]
            first_npz = npz_files[0] if npz_files else None

            copied_extra_json_paths = []
            copied_txt_path = None

            if flatten_fbx:
                if overwrite_mode == "overwrite":
                    for p in [final_fbx_path, final_npz_path, final_txt_path, final_log_path, final_meta_path]:
                        if p.exists():
                            try:
                                p.unlink()
                            except Exception:
                                pass

                shutil.copy2(first_fbx, final_fbx_path)

                if export_npz and first_npz and Path(first_npz).exists():
                    shutil.copy2(first_npz, final_npz_path)

                if export_txt:
                    candidate_txts = []
                    for p in txt_files:
                        low = p.name.lower()
                        if "summary" not in low and "batch_" not in low and ".log" not in low:
                            candidate_txts.append(p)
                    if candidate_txts:
                        shutil.copy2(candidate_txts[0], final_txt_path)
                        copied_txt_path = final_txt_path

                if export_extra_json:
                    extra_json_dir = category_dir / f"{final_name}_json"
                    extra_json_dir.mkdir(parents=True, exist_ok=True)
                    for p in json_files:
                        low = p.name.lower()
                        target = extra_json_dir / p.name
                        try:
                            shutil.copy2(p, target)
                            copied_extra_json_paths.append(str(target))
                        except Exception:
                            pass

                self._write_log(
                    final_log_path,
                    final_name=final_name,
                    category=safe_category,
                    prompt=prompt,
                    effective_prompt=effective_prompt,
                    preset=preset,
                    model_variant=model_variant,
                    duration_frames=duration_frames,
                    seed_mode=seed_mode,
                    num_seeds=num_seeds,
                    fixed_seed=fixed_seed,
                    overwrite_mode=overwrite_mode,
                    command=cmd,
                    return_code=result.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    warnings=warnings,
                )

                self._write_meta(
                    final_meta_path,
                    prompt=prompt,
                    effective_prompt=effective_prompt,
                    preset=preset,
                    model_variant=model_variant,
                    category=safe_category,
                    base_name=safe_base,
                    prefix=prefix,
                    suffix=suffix,
                    final_name=final_name,
                    duration_frames=duration_frames,
                    seed_mode=seed_mode,
                    num_seeds=num_seeds,
                    fixed_seed=fixed_seed,
                    overwrite_mode=overwrite_mode,
                    final_fbx_path=final_fbx_path,
                    final_npz_path=final_npz_path if (export_npz and first_npz) else None,
                    final_txt_path=copied_txt_path,
                    final_extra_json_paths=copied_extra_json_paths,
                    command=cmd,
                    return_code=result.returncode,
                    warnings=warnings,
                )

                if cleanup_temp:
                    try:
                        shutil.rmtree(run_output_dir, ignore_errors=True)
                    except Exception:
                        pass
                    try:
                        shutil.rmtree(input_dir, ignore_errors=True)
                    except Exception:
                        pass

                if open_output_folder:
                    open_folder_in_explorer(category_dir)

                with open(final_log_path, "r", encoding="utf-8") as f:
                    combined_log = f.read()

                return (
                    "SUCCESS",
                    str(final_fbx_path),
                    str(category_dir),
                    combined_log,
                    str(final_npz_path) if (export_npz and final_npz_path.exists()) else "",
                )

            temp_log_path = run_output_dir / f"{final_name}.log.txt"
            temp_meta_path = run_output_dir / f"{final_name}.meta.json"

            self._write_log(
                temp_log_path,
                final_name=final_name,
                category=safe_category,
                prompt=prompt,
                effective_prompt=effective_prompt,
                preset=preset,
                model_variant=model_variant,
                duration_frames=duration_frames,
                seed_mode=seed_mode,
                num_seeds=num_seeds,
                fixed_seed=fixed_seed,
                overwrite_mode=overwrite_mode,
                command=cmd,
                return_code=result.returncode,
                stdout=stdout,
                stderr=stderr,
                warnings=warnings,
            )

            self._write_meta(
                temp_meta_path,
                prompt=prompt,
                effective_prompt=effective_prompt,
                preset=preset,
                model_variant=model_variant,
                category=safe_category,
                base_name=safe_base,
                prefix=prefix,
                suffix=suffix,
                final_name=final_name,
                duration_frames=duration_frames,
                seed_mode=seed_mode,
                num_seeds=num_seeds,
                fixed_seed=fixed_seed,
                overwrite_mode=overwrite_mode,
                final_fbx_path=first_fbx,
                final_npz_path=first_npz if (export_npz and first_npz) else None,
                final_txt_path=None,
                final_extra_json_paths=[],
                command=cmd,
                return_code=result.returncode,
                warnings=warnings,
            )

            if open_output_folder:
                open_folder_in_explorer(run_output_dir)

            with open(temp_log_path, "r", encoding="utf-8") as f:
                combined_log = f.read()

            return (
                    "SUCCESS",
                    str(first_fbx),
                    str(run_output_dir),
                    combined_log,
                    str(first_npz) if (export_npz and first_npz and Path(first_npz).exists()) else "",
                )

        except Exception as e:
            return (
                f"ERROR: {str(e)}",
                "",
                str(final_output_root),
                "",
                "",
            )


NODE_CLASS_MAPPINGS = {
    "HYMotionRunner": HYMotionRunner
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HYMotionRunner": "HY-Motion Runner v6.2"
}