"""Скачивает GGUF моделей VLM-режима и готовит их для llama.cpp.

    python scripts/vlm/fetch_models.py <папка_моделей>

Запускается init-контейнером vlm-models (docker-compose.yml) или нативно
(scripts/vlm/setup.sh --native / setup.ps1 -Native). Нужны пакеты
huggingface_hub и gguf.

Каждая модель кладётся в <папка>/<имя_пресета>/ — пути совпадают с
scripts/vlm/models.ini. Файлы запинены по коммиту HF-репозитория (supply
chain: без плавающих ревизий). Уже скачанный файл повторно не качается.

VLM_MODELS (переменная окружения) — подмножество имён пресетов через запятую,
если на диске не нужны все пять моделей; пусто — все.

У PaddleOCR-VL в mmproj поднимается clip.vision.image_max_pixels до 1605632 —
официальное требование режима "Spotting:" для llama.cpp (README
PaddlePaddle/PaddleOCR-VL-1.6-GGUF: gguf_set_metadata.py ... --force).
"""

import os
import subprocess
import sys

# имя пресета: (HF-репозиторий, коммит, [модель, mmproj])
MODELS = {
    "paddleocr-vl": (
        "PaddlePaddle/PaddleOCR-VL-1.6-GGUF",
        "511b09642bb324401f15f97cc23bc67e8f0a291d",
        ["PaddleOCR-VL-1.6-GGUF.gguf", "PaddleOCR-VL-1.6-GGUF-mmproj.gguf"],
    ),
    "hunyuan-ocr": (
        "ggml-org/HunyuanOCR-GGUF",
        "8e070c9ad79e4ca97a9b4daa2f1ce17e8759afb1",
        ["HunyuanOCR-Q8_0.gguf", "mmproj-HunyuanOCR-Q8_0.gguf"],
    ),
    "glm-ocr": (
        "ggml-org/GLM-OCR-GGUF",
        "65a42de1148dbed2297e922b5dbc7d9b70c36578",
        ["GLM-OCR-Q8_0.gguf", "mmproj-GLM-OCR-Q8_0.gguf"],
    ),
    "dots-ocr": (
        "ggml-org/dots.ocr-GGUF",
        "2c093a32ca360a396bc6d87d60408636130b9d9b",
        ["dots.ocr-Q8_0.gguf", "mmproj-dots.ocr-Q8_0.gguf"],
    ),
    "unlimited-ocr": (
        "sahilchachra/Unlimited-OCR-GGUF",
        "0dc781d8a23f52963918ebd5b2d1b9fe61504661",
        ["Unlimited-OCR-Q8_0.gguf", "mmproj-Unlimited-OCR-F16.gguf"],
    ),
}

PADDLE_MMPROJ = ("paddleocr-vl", "PaddleOCR-VL-1.6-GGUF-mmproj.gguf")
SPOTTING_MAX_PIXELS_KEY = "clip.vision.image_max_pixels"
SPOTTING_MAX_PIXELS = 1605632


def selected_models(env_value: str) -> list:
    """Имена пресетов из VLM_MODELS (через запятую); пусто — все."""
    names = [name.strip() for name in env_value.split(",") if name.strip()]
    if not names:
        return list(MODELS)
    unknown = sorted(set(names) - set(MODELS))
    if unknown:
        raise SystemExit(f"Неизвестные модели в VLM_MODELS: {unknown}; доступны: {list(MODELS)}")
    return names


def download(dest_root: str, name: str) -> None:
    from huggingface_hub import hf_hub_download

    repo, revision, files = MODELS[name]
    target_dir = os.path.join(dest_root, name)
    for filename in files:
        path = os.path.join(target_dir, filename)
        if os.path.isfile(path):
            print(f"[{name}] уже есть: {filename}", flush=True)
            continue
        print(f"[{name}] скачиваю {repo}@{revision[:10]}/{filename} ...", flush=True)
        hf_hub_download(repo, filename, revision=revision, local_dir=target_dir)


def _read_int_field(path: str, key: str):
    from gguf import GGUFReader

    field = GGUFReader(path).get_field(key)
    if field is None:
        return None
    return int(field.parts[field.data[0]][0])


def patch_paddle_mmproj(dest_root: str) -> None:
    """Spotting у PaddleOCR-VL в llama.cpp требует image_max_pixels = 1605632."""
    name, filename = PADDLE_MMPROJ
    path = os.path.join(dest_root, name, filename)
    current = _read_int_field(path, SPOTTING_MAX_PIXELS_KEY)
    if current is None:
        raise SystemExit(f"В {path} нет ключа {SPOTTING_MAX_PIXELS_KEY} — формат mmproj изменился")
    if current == SPOTTING_MAX_PIXELS:
        print(f"[{name}] {SPOTTING_MAX_PIXELS_KEY} уже {current}", flush=True)
        return
    print(f"[{name}] {SPOTTING_MAX_PIXELS_KEY}: {current} -> {SPOTTING_MAX_PIXELS}", flush=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "gguf.scripts.gguf_set_metadata",
            path,
            SPOTTING_MAX_PIXELS_KEY,
            str(SPOTTING_MAX_PIXELS),
            "--force",
        ],
        check=True,
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: fetch_models.py <папка_моделей>")
    dest_root = sys.argv[1]
    names = selected_models(os.environ.get("VLM_MODELS", ""))
    for name in names:
        download(dest_root, name)
    if PADDLE_MMPROJ[0] in names:
        patch_paddle_mmproj(dest_root)
    print(f"Готово: {', '.join(names)}", flush=True)


if __name__ == "__main__":
    main()
