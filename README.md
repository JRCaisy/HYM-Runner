# HY-Motion Runner (ComfyUI Custom Node)

## Overview

**HY-Motion Runner** is a custom ComfyUI node that enables fully local **text-to-motion → FBX animation generation** using HY-Motion-1.0.

It acts as a bridge between:

* HY-Motion CLI (Python-based backend)
* ComfyUI node-based workflows
* Unreal Engine-ready animation pipelines

This node is designed with **production workflows** in mind, focusing on clean output structure, deterministic naming, metadata tracking, and full offline operation.

---

## Features

* ✅ Fully local execution (no cloud dependency)
* ✅ Direct FBX export
* ✅ Category-based folder organization
* ✅ Prefix / suffix naming system
* ✅ Incremental numbering using `#`
* ✅ External preset library (`.json`)
* ✅ Per-animation `.log.txt` and `.meta.json`
* ✅ Automatic temporary folder cleanup
* ✅ Optional auto-open output folder
* ✅ Stable CLI-based HY-Motion integration

---

## Requirements

* **ComfyUI**
* **HY-Motion-1.0 (local installation)**
* **Python 3.10+**
* A dedicated **virtual environment (venv)**
* HY-Motion model checkpoints
* FBX export working correctly

---

## Official References

* HY-Motion-1.0 (Official Repository):
  https://github.com/Tencent-Hunyuan/HY-Motion-1.0

* Python Downloads:
  https://www.python.org/downloads/

* Python `venv` Documentation:
  https://docs.python.org/3/library/venv.html

* ComfyUI Custom Node Installation Guide:
  https://docs.comfy.org/installation/install_custom_node

---

## Dependencies

HY-Motion requires specific versions of key libraries, including:

* `torch`
* `torchvision`
* `transformers`
* `diffusers`
* `accelerate`
* `huggingface_hub`

Install all dependencies via HY-Motion’s official:

```bash
pip install -r requirements.txt
```

---

## Model Checkpoints

HY-Motion expects a local checkpoint structure similar to:

```text
ckpts/
├── tencent/
│   ├── HY-Motion-1.0/
│   └── HY-Motion-1.0-Lite/
├── clip-vit-large-patch14/
├── Qwen3-8B/
└── Text2MotionPrompter/ (optional)
```

---

## Installation

### 1. Install HY-Motion

Follow the official HY-Motion setup:

1. Install PyTorch
2. Clone repository
3. Run:

```bash
git lfs pull
```

4. Install dependencies:

```bash
pip install -r requirements.txt
```

---

### 2. Create a Virtual Environment

Recommended:

```bash
python -m venv venv
```

Activate and install dependencies inside it.

---

### 3. Install the Custom Node

#### Generic ComfyUI Path

```text
ComfyUI/custom_nodes/
```

#### Desktop App Example (Tested Setup)

```text
ComfyUI/resources/ComfyUI/custom_nodes/hy_motion_runner
```

Place files:

```text
hy_motion_runner/
├── __init__.py
├── hy_motion_node.py
└── preset_library.json
```

---

### 4. Configure HY-Motion Path

Edit inside the node:

```python
hy_root = Path(r"E:\AI\HY-Motion-1.0")
```

---

### 5. Configure Output Directory

```python
final_output_root = Path(r"E:\GRapHiC\Animations\HYM")
```

---

### 6. Restart ComfyUI

Fully restart after installation.

---

## Usage

### Core Inputs

| Input             | Description                |
| ----------------- | -------------------------- |
| `prompt`          | Custom motion description  |
| `preset`          | Predefined motion template |
| `category`        | Output folder group        |
| `base_name`       | Base animation name        |
| `prefix`          | Prepended string           |
| `suffix`          | Appended string            |
| `duration_frames` | Animation length           |
| `seed_mode`       | Random or fixed            |
| `num_seeds`       | Variation count            |
| `overwrite_mode`  | next / overwrite / skip    |

---

## Naming System

Supports incremental numbering via `#`.

### Example

```text
prefix = A_Stalker_
base_name = HeartAttack
suffix = _v##
```

Output:

```text
A_Stalker_HeartAttack_v01.fbx
A_Stalker_HeartAttack_v02.fbx
A_Stalker_HeartAttack_v03.fbx
```

---

## Output Structure

```text
E:\GRapHiC\Animations\HYM\
 └── Death\
     ├── A_Stalker_HeartAttack_v01.fbx
     ├── A_Stalker_HeartAttack_v01.log.txt
     ├── A_Stalker_HeartAttack_v01.meta.json
```

---

## Preset Library

Stored in:

```text
preset_library.json
```

Example:

```json
{
  "jump": "A person jumps upward with both legs once.",
  "death": "A person collapses to the ground dramatically."
}
```

Reload dynamically:

```text
reload_preset_library = True
```

---

## Meta File

Each animation generates:

```json
{
  "prompt": "...",
  "effective_prompt": "...",
  "model_variant": "...",
  "duration_frames": 150,
  "final_fbx_path": "...",
  "command": [...]
}
```

### Purpose

* Debugging
* Reproducibility
* Pipeline tracking

---

## Overwrite Modes

| Mode        | Behavior          |
| ----------- | ----------------- |
| `next`      | Uses next index   |
| `overwrite` | Replaces existing |
| `skip`      | Skips generation  |

---

## Known Limitations

* Does NOT generate custom rigs
* Uses built-in humanoid skeleton (SMPL-based)
* Requires retargeting for custom characters

### Important Note

HY-Motion may output warnings such as:

```
No SMPL data found...
```

This does **NOT prevent FBX generation**. The animation is still exported successfully.

---

## Unreal Engine Workflow

1. Import FBX
2. Assign skeleton
3. Retarget if needed
4. Use in Animation Blueprint

---

## Recommended External Links

* HY-Motion-1.0 Repository
  https://github.com/Tencent-Hunyuan/HY-Motion-1.0

* Python Official Downloads
  https://www.python.org/downloads/

* Python Virtual Environment Docs
  https://docs.python.org/3/library/venv.html

* ComfyUI Custom Nodes Guide
  https://docs.comfy.org/installation/install_custom_node

---

## Roadmap

* Batch processing
* Deterministic seed control
* UI tooltips / field descriptions
* Preset categorization
* Advanced prompt composition

---

## Philosophy

This tool is built for:

* Developers building pipelines
* Game developers integrating AI animation
* Artists working with iterative workflows

It prioritizes:

* Stability
* Clarity
* Control

---

## License

Free for use and modification.

---

## Credits

* HY-Motion by Tencent
* ComfyUI ecosystem
* Developed by Caisy & Aki

---

## Final Note

This is not just a node.

It is a **bridge between AI motion generation and real production pipelines**.
