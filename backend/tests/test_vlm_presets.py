"""Согласованность трёх мест, которые обязаны совпадать: пресеты llama-server
(scripts/vlm/models.ini), скачиваемые файлы (scripts/vlm/fetch_models.py) и
имена моделей в запросах backend'а (VLM_ENGINE_META[...]["served_model_name"])."""

import configparser
import importlib.util
from pathlib import Path

from backend.config import VLM_ENGINE_META, VLM_ENGINES

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "vlm"


def _presets():
    # llama.cpp допускает ключи до первой секции (version = 1) — configparser нет.
    parser = configparser.ConfigParser(comment_prefixes=(";",))
    text = (SCRIPTS / "models.ini").read_text(encoding="utf-8")
    parser.read_string("[__top__]\n" + text)
    return {name: dict(parser[name]) for name in parser.sections() if name not in ("*", "__top__")}


def _fetch_models():
    spec = importlib.util.spec_from_file_location("fetch_models", SCRIPTS / "fetch_models.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_engine_has_a_preset_and_nothing_extra():
    served = {VLM_ENGINE_META[e]["served_model_name"] for e in VLM_ENGINES}

    assert set(_presets()) == served


def test_preset_paths_match_downloaded_files():
    fetch = _fetch_models()

    for name, preset in _presets().items():
        _, revision, files = fetch.MODELS[name]
        assert len(revision) == 40, name  # запинено по коммиту, не по ветке
        expected = {f"/models/{name}/{filename}" for filename in files}
        assert {preset["model"], preset["mmproj"]} == expected, name


def test_paddle_mmproj_patched_is_the_preset_mmproj():
    fetch = _fetch_models()
    name, filename = fetch.PADDLE_MMPROJ

    assert _presets()[name]["mmproj"] == f"/models/{name}/{filename}"
