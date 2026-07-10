import copy
from pathlib import Path

import yaml

DEFAULTS = {
    "meetings_dir": "meetings",
    "recording": {"chunk_seconds": 60, "min_free_gb": 2.0},
    "kaggle": {
        "username": "",
        "dataset_slug": "marwin-inbox",
        "kernel_slug": "marwin-processor",
        "keep_audio": False,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(root: Path) -> dict:
    cfg_path = Path(root) / "config.yaml"
    if cfg_path.exists():
        try:
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise RuntimeError(f"config.yaml is not valid YAML: {e}") from e
        if not isinstance(loaded, dict):
            raise RuntimeError(
                "config.yaml must contain key: value settings (see config.example.yaml)")
        return _merge(DEFAULTS, loaded)
    return copy.deepcopy(DEFAULTS)
