from pathlib import Path
import pytest
from marwin.config import load_config

def test_defaults_without_yaml(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg["recording"]["chunk_seconds"] == 60
    assert cfg["recording"]["min_free_gb"] == 2.0
    assert cfg["kaggle"]["dataset_slug"] == "marwin-inbox"
    assert cfg["kaggle"]["keep_audio"] is False
    assert cfg["meetings_dir"] == "meetings"

def test_yaml_overrides_deep_merge(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "kaggle:\n  username: vania\nrecording:\n  chunk_seconds: 30\n"
    )
    cfg = load_config(tmp_path)
    assert cfg["kaggle"]["username"] == "vania"
    assert cfg["recording"]["chunk_seconds"] == 30
    assert cfg["recording"]["min_free_gb"] == 2.0  # untouched default

def test_invalid_yaml_raises_friendly_error(tmp_path):
    (tmp_path / "config.yaml").write_text("kaggle: [unclosed")
    with pytest.raises(RuntimeError, match="not valid YAML"):
        load_config(tmp_path)

def test_non_dict_yaml_raises_friendly_error(tmp_path):
    (tmp_path / "config.yaml").write_text("just a string")
    with pytest.raises(RuntimeError, match="config.example.yaml"):
        load_config(tmp_path)
