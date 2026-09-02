# Отдельный VLM-режим для OCR: обзор компактных моделей (≤ 2B)

> Исследование под задачу: добавить в `backend/` отдельный VLM-режим авторазметки —
> end-to-end VLM обрабатывает страницу целиком и отдаёт боксы строк + текст, наряду с
> текущим построчным консенсусом PaddleOCR + Surya + Tesseract.
> Дата обзора: 2026-08-30, обновлено 2026-09-02. Все цифры — из публичных техотчётов и
> карточек моделей (ссылки внизу); бенчмарки авторские, воспроизводимость на нашем
> контенте отдельно.
>
> **Обновление 2026-09-02 (по итогам уточнений заказчика):**
> - `onnx-community/GLM-OCR-ONNX` **существует** (MIT; vision_encoder + decoder_model_merged
>   + embed_tokens; варианты fp16 / q4 / q4f16 / quantized) — GLM-OCR больше не «без ONNX».
> - HunyuanOCR: ограничение лицензии по ЕС / Великобритании / Южной Корее **заказчику не
>   применимо** → HunyuanOCR берём как полноценный CPU-движок. Есть путь llama.cpp
>   (GGUF base + mmproj → llama-server, OpenAI-совместимо), у HunyuanOCR-1.5 — ускорение DFlash.
> - Granite-Docling **не поддерживает русский** (в осн. английский) → из шорт-листа под
>   наш RU-контент исключён.
> - Выбранная архитектура режима — **единый OpenAI-совместимый HTTP** ко всем моделям
>   (llama-server / Ollama / vLLM как внешние сервисы). См. план:
>   `.claude/PRPs/plans/vlm-ocr-mode.plan.md`.
> - Референс реализации GLM-пути — **Folio-OCR** (FastAPI → Ollama HTTP + PP-DocLayoutV3 +
>   слияние регионов + постпроцесс markdown), MIT.

---

## 1. Короткий вывод

### Итоговый набор движков режима (после уточнений)

| Класс | Движки | Транспорт |
|---|---|---|
| **CPU (основные)** | **PaddleOCR-VL** (0.9B, Apache-2.0), **GLM-OCR** (0.9B, MIT), **HunyuanOCR-1.5** (1B) | OpenAI-совместимый HTTP: vLLM / Ollama / llama.cpp llama-server |
| **GPU (доп., если есть карта)** | **dots.ocr / dots.mocr** (3B, MIT, поддерживает русский), **baidu/Unlimited-OCR** (3B MoE / 500M активных, MIT, линейка DeepSeek-OCR) | тот же HTTP: vLLM ≥ 0.11.0 / SGLang |

### Прежние общие рекомендации (для контекста)

| Что нужно | Рекомендация |
|---|---|
| Лучшая точность + готовый ONNX на CPU | **PaddleOCR-VL-1.6 (0.9B)** — Apache-2.0, 109 языков (кириллица), `onnx-community` INT8/INT4 |
| Топ OmniDocBench, либеральная лицензия | **GLM-OCR (0.9B, веса MIT)** — ONNX есть (`onnx-community/GLM-OCR-ONNX`), плюс Ollama/vLLM |
| SOTA на 1.2B (осторожно с лицензией весов) | **MinerU2.5-Pro (1.2B)** — веса AGPL-3.0 ⚠️ |
| Лёгкий edge/браузер, НО английский | **Granite-Docling-258M** — Apache-2.0, ONNX + transformers.js; для RU не подходит |

**Про ONNX на CPU честно:** официальные ONNX-релизы «из коробки» есть у PaddleOCR-VL,
**GLM-OCR** и Granite-Docling.
Остальные — либо через GGUF/llama.cpp (GLM-OCR через Ollama), либо ручной экспорт
`torch.onnx` / `optimum`, который для VLM с динамическим разрешением болезненный
(динамические оси, кастомные position embeddings, упаковка image-токенов). На CPU при
любом варианте закладывайтесь на **3–30 секунд на страницу** и обязательный
квантованный движок (OpenVINO / ORT-INT8 / llama.cpp). Голый PyTorch на CPU — неюзабельно.

---

## 2. Шорт-лист (5 моделей до 2B)

### 2.1 PaddleOCR-VL-1.6 — 0.9B ⭐ основной кандидат

| | |
|---|---|
| Параметры | ~0.9B: NaViT-энкодер с динамическим разрешением + ERNIE-4.5-0.3B (декодер) |
| Задача | Полный парсинг документа: текст, таблицы, формулы, диаграммы, чтение-порядок |
| Языки | 109, включая кириллицу |
| Лицензия | **Apache-2.0** |
| OmniDocBench | v1.5: 0.9B — 92.56 → 1.5 — 94.5 → **1.6 — 96.34** (v1.6_full); Text Edit 0.033; Formula CDM 97.5; Table TEDS 94.8 |
| Позиционирование авторов | обходит GPT-4o / Gemini 2.5 Pro на парсинге документов |
| VRAM (FP16) | ~2 ГБ |
| Скорость (GPU) | ~1.2 pages/s (A100, техотчёт); ~2.0 pages/s (A100 + FastDeploy, v1.5) |
| **ONNX / CPU** | **`onnx-community/PaddleOCR-VL-1.5-ONNX`** — раздельные ONNX: энкодер (FP32 / INT8-dynamic / INT4 NNCF data-free) + декодер (FP32 / INT8 / INT4 GPTQ) + общий `embed.onnx`. Демо на **OpenVINO** (Colab). PaddleOCR core официально поддерживает ONNX Runtime / OpenVINO / TensorRT и конвертацию `paddle2onnx`. Публичных цифр «с/страница на CPU» нет — мерить самим |

**Плюсы:** лучший баланс точность/размер/лицензия; единственный с реальным ONNX-релизом;
кириллица заявлена; активный релизный цикл (0.9B → 1.5 → 1.6).
**Минусы:** энкодер с динамическим разрешением → большой prefill на плотных страницах;
CPU-латентность не опубликована; ONNX-репо ещё «молодое» (низкие загрузки, мало отзывов).

---

### 2.2 GLM-OCR — 0.9B (Z.ai / zai-org)

| | |
|---|---|
| Параметры | 0.9B: CogViT-энкодер 0.4B + GLM-декодер 0.5B |
| Фишка | **Multi-Token Prediction (MTP)** — предсказывает несколько токенов за шаг, ускоряет детерминированное OCR-декодирование при малом оверхеде памяти |
| Лицензия | код — Apache-2.0, **веса — MIT** (самая либеральная в списке); layout-модуль pipeline (PP-DocLayoutV3) — Apache-2.0 |
| OmniDocBench v1.5 | **Overall 94.62** — 1-е место на момент выхода (выше PaddleOCR-VL-1.5 94.50, MinerU2.5, Qwen3-VL-235B, Gemini-3 Pro) |
| OCRBench (Text) | 94.0 |
| Деплой | vLLM, SGLang, **Ollama** (`ollama pull glm-ocr`, OpenAI-совместимо на `:11434/v1`); 2–4 ГБ VRAM FP16; CPU — через Ollama/llama.cpp |
| **ONNX** | **есть** — `onnx-community/GLM-OCR-ONNX` (MIT): `vision_encoder` + `decoder_model_merged` + `embed_tokens`, варианты `fp16` / `q4` / `q4f16` / `quantized`; `transformers.js`-совместимо. Сам VLM отдаёт **markdown без боксов** — боксы строк даёт PP-DocLayoutV3 (в pipeline GLM-OCR) либо наш `backend/detector.py` |
| Отчёт | arXiv 2603.10910 |

**Плюсы:** топ-точность, лицензия MIT на веса, MTP-ускорение, есть Ollama-путь на CPU.
**Минусы:** нет ONNX; для нашего «CPU + возможно .exe» сценария остаётся только llama.cpp.

---

### 2.3 MinerU2.5-Pro — 1.2B (OpenDataLab)

| | |
|---|---|
| Параметры | 1.2B: NaViT-энкодер 0.675B (из Qwen2-VL) + patch merger + Qwen2-Instruct 0.5B |
| Архитектура | **двухстадийный coarse-to-fine**: (1) уменьшенная страница → глобальный layout, (2) кропы в высоком разрешении → точный парсинг. Экономит токены на плотных страницах |
| OmniDocBench v1.6 | MinerU2.5 ~90.7 (по отчёту GLM); **MinerU2.5-Pro-2604 — 95.69** (SOTA, только за счёт data engineering, архитектура зафиксирована) |
| Лицензия | фреймворк — «MinerU Open Source License» (на базе Apache-2.0 + доп. условия); **веса `MinerU2.5-2509-1.2B` — AGPL-3.0** ⚠️ (для Pro-чекпойнта уточнить отдельно) |
| Деплой | vLLM, transformers, SGLang; **официального ONNX нет**, но Qwen2-backbone в принципе конвертируем |
| Отчёт | arXiv 2509.22186 / 2604.04771 |

**Плюсы:** SOTA-точность на 1.2B; двухстадийность → меньше токенов → потенциально быстрее на CPU.
**Минусы:** AGPL на весах — токсично для проприетарного/закрытого использования, ОК только если весь проект под совместимой лицензией; ONNX нет; ориентация на zh/en.

---

### 2.4 HunyuanOCR-1.5 — 1B (Tencent) — CPU-движок набора

| | |
|---|---|
| Параметры | 1B: Native-resolution ViT + адаптивный MLP-адаптер + лёгкий Hunyuan-LLM |
| Возможности | детекция + распознавание + парсинг + перевод + извлечение полей в одном проходе |
| OmniDocBench | v1 — 94.1; **v1.6 (HunyuanOCR-1.5) — 94.74** (SOTA среди end-to-end expert-моделей) |
| OCRBench | 860 — SOTA среди VLM < 3B |
| Награды | 1-е место ICDAR 2025 DIMT Challenge (Small Model Track) |
| Скорость | DFlash: ×6.37 к transformers, ×2.14 к vLLM; в vLLM латентность 3.03s → 1.41s, throughput 467 → 1002 tok/s |
| **Лицензия** | веса открыты; запрет на использование в ЕС / Великобритании / Южной Корее — **заказчику не применимо** |
| ONNX | официально нет; **CPU — через llama.cpp: GGUF (base + mmproj) → llama-server, OpenAI-совместимо**; также transformers / vLLM |
| Промпт text spotting | `"Detect and recognize text in the image, and output the text coordinates in a formatted manner."` → формат `text(x1,y1),(x2,y2)` — готовый grounding для нарезки строк |
| Отчёт | arXiv 2511.19575 / 2607.04884 |

**Вывод:** один из лучших в классе 1B; для нашей юрисдикции ограничений нет. Берём как
CPU-движок набора через llama-server (GGUF). Text-spotting промпт сразу даёт боксы+текст.

---

### 2.5 Granite-Docling-258M — 258M (IBM) ⭐ лёгкий кандидат

| | |
|---|---|
| Параметры | 258M: SigLIP2-base-patch16-512 (vision) + Granite-165M (LM), архитектура Idefics3; преемник SmolDocling-256M |
| Выход | **DocTags** (компактный структурный формат) → далее в Markdown / HTML / JSON |
| Лицензия | **Apache-2.0** |
| Языки | в основном английский; ar/zh/ja — экспериментально. Кириллица слабо |
| OmniDocBench | официально не заявляли; позиционируется на уровне/выше SmolDocling |
| **ONNX / CPU** | **`onnx-community/granite-docling-258M-ONNX`** + **`transformers.js`** (CPU / WebGPU / WASM, работает в браузере) + **GGUF** для llama.cpp / LM Studio. ONNX ~×3.1 к PyTorch (0.8s vs 2.5s), RAM ~1.8 ГБ вместо 4.2 ГБ, загрузка ~×2.7 |
| Осторожно | голый `transformers` на CPU очень медленный (тайлинг картинки → много prefill-токенов + медленный препроцессинг); переход на llama.cpp у пользователей давал до ×100 (5 мин → 3 с) |

**Плюсы:** реально запускается на CPU и даже в браузере; крошечный; Apache-2.0; можно
бандлить рядом с фронтенд-.exe.
**Минусы:** потолок точности ниже; слабая мультиязычность (для RU-контента —
скорее вспомогательный, не основной); чувствителен к движку инференса.

---

## 3. Сводная таблица

| Модель | Параметры | Энкодер + LLM | Лицензия | OmniDocBench (лучшая опубл.) | OCRBench | Офиц. ONNX | CPU-путь | RU / кириллица |
|---|---|---|---|---|---|---|---|---|
| **PaddleOCR-VL-1.6** | 0.9B | NaViT + ERNIE-4.5-0.3B | Apache-2.0 | **96.34** (v1.6) | — | **да** (onnx-community, INT8/INT4) | OpenVINO / ORT | да (109 языков) |
| **GLM-OCR** | 0.9B | CogViT-0.4B + GLM-0.5B | код Apache-2.0 / веса **MIT** | **94.62** (v1.5) | 94.0 | нет | Ollama / llama.cpp (GGUF) | да (мультиязычная) |
| **MinerU2.5-Pro** | 1.2B | NaViT-0.675B (Qwen2-VL) + Qwen2-0.5B | фреймворк ~Apache / **веса AGPL-3.0** ⚠️ | **95.69** (v1.6) | — | нет | ручной экспорт (Qwen2) | ограниченно (zh/en) |
| **HunyuanOCR-1.5** | 1B | Native ViT + Hunyuan-LLM | открытая (ЕС/UK/KR — нам ок) | **94.74** (v1.6) | 860 | нет (llama.cpp GGUF) | llama-server / vLLM | да (spotting-промпт) |
| **Granite-Docling-258M** | 258M | SigLIP2 + Granite-165M | Apache-2.0 | не заявлен | — | **да** (onnx-community + transformers.js + GGUF) | ONNX / llama.cpp / браузер | ❌ слабо (в осн. EN) |
| **dots.ocr** (GPU) | 3B | 1.2B vision + Qwen3-VL | **MIT** | выше спец-OCR (v1.5) | — | нет | vLLM ≥ 0.11 | ✅ да |
| **Unlimited-OCR** (GPU) | 3B MoE / 500M акт. | DeepEncoder (SAM+CLIP) + MoE-декодер R-SWA | **MIT** | — | — | нет | vLLM / SGLang | частично |

*OCRBench: значения в разных отчётах нормируются по-разному (0–100 против 0–1000) — сверять шкалу при прямом сравнении.*
*«Офиц. ONNX = нет (llama.cpp GGUF)» означает: ONNX-релиза нет, но CPU-путь есть через GGUF.*

---

## 4. За рамками бюджета ≤ 2B (для контекста)

| Модель | Параметры | Заметки |
|---|---|---|
| **dots.ocr / dots.mocr** ✅ в наборе (GPU) | 3B (1.2B vision + Qwen3-VL-осн.) | studio-dots-ai, **MIT**, **поддерживает русский/кириллицу**; выход — **JSON `[{bbox:[x1,y1,x2,y2], category, text}]`** (layout+текст за один проход — идеальный grounding); vLLM ≥ 0.11.0 OpenAI-совместимо, Docker-образы; olmOCR-bench 83.9; вариант `dots.mocr-svg` для image→SVG |
| **baidu/Unlimited-OCR** ✅ в наборе (GPU) | 3B MoE / 500M активных | Линейка DeepSeek-OCR: vision-стек gundam (SAM-ViT-B + CLIP-L), декодер MoE с Reference Sliding Window Attention; **MIT**; режимы `gundam` (640, crop) / `base` (1024); выход — **grounded markdown с токенами `<ref>…</ref><box>…</box>`**; transformers / vLLM / SGLang; arXiv 2606.23050 |
| **DeepSeek-OCR / DeepSeek-OCR-2** | ~3B MoE (~570M активных; DeepEncoder ~380M) | родоначальник линейки Unlimited-OCR; «оптическая компрессия контекста», grounded Markdown; официального ONNX нет, есть community CPU-форки (`DeepSeek-OCR-CPU`) |
| **Nanonets-OCR2-3B** | 3B | структурный вывод, таблицы/чарты/рукопись |
| **Chandra 2** (Datalab, авт. Marker/Surya) | ~4B (было 9B в v1) | HTML/MD/JSON с сохранением layout, 90 языков; olmOCR-bench 85.9; уже в Azure AI Foundry |
| **olmOCR-2** | 7B | unit-test rewards; сильный, но большой |
| **PP-OCRv5** | ~5M (не VLM) | классический pipeline детекция+распознавание; полезен как быстрый baseline / часть консенсуса, не VLM-режим |

Если ограничение «≤ 2B» можно ослабить до «≤ 3B общих / ≤ 1B активных», **DeepSeek-OCR**
и **dots.ocr** становятся сильными кандидатами для GPU-инференса.

---

## 5. ONNX-инференс на CPU: детальнее

### Что работает сейчас
- **PaddleOCR-VL** — официальный ONNX-релиз с квантизацией (INT8 dynamic, INT4 NNCF/GPTQ),
  демо на OpenVINO. Плюс PaddleOCR core умеет `paddle2onnx` → ORT/OpenVINO/TensorRT.
- **Granite-Docling-258M** — `onnx-community` + `transformers.js` (даже WASM в браузере) + GGUF.

### ONNX-релиз есть
- **GLM-OCR** — `onnx-community/GLM-OCR-ONNX` (MIT): `vision_encoder` + `decoder_model_merged`
  + `embed_tokens`, варианты `fp16` / `q4` / `q4f16` / `quantized`; transformers.js-совместимо.

### Что через GGUF / llama.cpp (не ORT)
- **GLM-OCR** — также через Ollama (`ollama pull glm-ocr`, официально поддержан).
- **HunyuanOCR-1.5** — GGUF (base + mmproj) → llama-server, официальный путь «PC-side».
- **Granite-Docling** — GGUF для llama.cpp / LM Studio.
- MinerU / dots.ocr — по мере появления community-GGUF.

### Ручной экспорт (ожидать возню)
VLM с динамическим разрешением плохо экспортируются в чистый ONNX:
- динамические оси и переменное число image-токенов;
- кастомные rotary / 2D position embeddings;
- препроцессинг (тайлинг, ресайз) остаётся вне графа и часто сам по себе медленный;
- удобнее экспортировать vision-энкодер и LLM-декодер **раздельно** (как и сделал
  onnx-community для PaddleOCR-VL).

### Ориентиры производительности
- Голый `transformers` на CPU: **десятки секунд — минуты** на страницу (Granite-Docling:
  до 5 мин у пользователей).
- llama.cpp / OpenVINO / ORT-INT8: от **~1–3 с** (крошечные модели) до **~10–30 с**
  (0.9–1.2B на плотной A4 в высоком разрешении) на десктопном CPU.
- Прямое сравнение с текущим пайплайном (Paddle/Surya/Tesseract на CPU) надо снять на
  нашем корпусе — заявленные цифры даны на GPU.

---

## 6. Замечания по интеграции в `backend/` (выбранная архитектура)

Подробный план: **`.claude/PRPs/plans/vlm-ocr-mode.plan.md`**. Кратко:

- **Отдельный путь авторазметки**, не участник построчного консенсуса. Новый тип job'а
  (`mode="vlm"` в `/run`), новый `backend/pipeline_vlm.py` с той же сигнатурой
  callback'ов, что у `pipeline.run` (`on_found/on_file_done/on_line_done/on_error/
  should_cancel`) — `jobs.py` выбирает `run_fn` по `mode`, `JobState` общий.
- **VLM обрабатывает страницу/регион целиком** за один forward и сам отдаёт
  `(полигон строки, текст)`. Grounding: dots.ocr — JSON с `bbox`; HunyuanOCR — spotting-
  промпт `text(x1,y1),(x2,y2)`; PaddleOCR-VL — pipeline с layout; GLM-OCR — боксы от
  PP-DocLayoutV3 / нашего `detector.py`; Unlimited-OCR — токены `<box>`.
- **Единый транспорт — OpenAI-совместимый HTTP** (`/v1/chat/completions` c `image_url`).
  Модели поднимаются **внешними сервисами**: vLLM / Ollama (`glm-ocr`) / llama.cpp
  llama-server (HunyuanOCR GGUF). Backend тяжёлых ML-зависимостей VLM **не тянет** —
  единственная новая зависимость `httpx`.
- Новые модули: `vlm_client.py` (HTTP), `vlm_adapters.py` (промпты + парсеры ответов),
  `vlm_layout.py` (боксы для GLM-стратегии, ленивый импорт, без юнит-тестов — как
  `detector.py`), `vlm_consensus.py` (IoU-сопоставление боксов + `vote()` из
  `consensus.py`), `pipeline_vlm.py`.
- Выход — **те же** `good.txt` / `needs_review.txt` / `debug.jsonl` / `crops/`, поэтому
  handoff в ручную разметку работает без изменений. `score` в `debug.jsonl` = 1.0
  (VLM per-line confidence не дают); `diverged` — по несовпадению текстов ≥2 движков.
- Несколько VLM → консенсус по IoU-группировке боксов + текстовое голосование
  (`vlm_min_agree`, `iou_threshold` вместо `score_threshold`).
- Docker: опциональные compose-профили companion-сервисов (`--profile vlm-cpu` /
  `--profile vlm-gpu`), по умолчанию не поднимаются.
- Языки: дефолт VLM-движка — **PaddleOCR-VL** (кириллица, Apache-2.0).

---

## 7. Рекомендуемый порядок работ

1. **Каркас** (Tasks 1–10 плана): `config` реестр → `vlm_client` → `vlm_adapters` →
   `vlm_consensus` → `pipeline_vlm` → проводка в `jobs`/`main`/`models_status` → `httpx`.
2. **PoC на GLM-OCR через Ollama** (`ollama pull glm-ocr`) на CPU: 20–30 реальных
   страниц, снять точность vs классический консенсус, секунд/страница, RAM.
3. **Добавить PaddleOCR-VL и HunyuanOCR-1.5** (vLLM / llama-server GGUF), сравнить на том
   же наборе; выбрать дефолт.
4. **dots.ocr + Unlimited-OCR** — включить, если есть GPU; тесты на фикстурах ответов,
   не на живой модели.
5. **Фронтенд** (Task 15): радио «Классический / VLM» + форма моделей.
6. **Провижининг** (Task 16): Docker-профили `vlm-cpu`/`vlm-gpu` + `scripts/vlm/setup.sh`
   и `setup.ps1` (заказчик на Win10). Готовые артефакты: `ollama pull glm-ocr` (офиц.),
   `MedAIBase/PaddleOCR-VL:0.9b` (community Ollama), `ggml-org/HunyuanOCR-GGUF` (офиц.
   llama.cpp, `llama-server -hf ...`).
7. **Документация** (Task 17), ручная верификация e2e (Task 18).

---

## Источники

- [PaddleOCR-VL: 0.9B ultra-compact VLM (arXiv 2510.14528)](https://arxiv.org/html/2510.14528v1)
- [PaddleOCR-VL-1.5 (arXiv 2601.21957)](https://arxiv.org/pdf/2601.21957)
- [onnx-community/PaddleOCR-VL-1.5-ONNX](https://huggingface.co/onnx-community/PaddleOCR-VL-1.5-ONNX)
- [PaddleOCR High-Performance Inference docs (ONNX/OpenVINO/TensorRT)](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/deployment/high_performance_inference.html)
- [PaddlePaddle/PaddleOCR-VL (HF)](https://huggingface.co/PaddlePaddle/PaddleOCR-VL)
- [GLM-OCR Technical Report (arXiv 2603.10910)](https://arxiv.org/abs/2603.10910)
- [GLM-OCR performance on OmniDocBench v1.5](https://arxiv.org/html/2603.10910)
- [zai-org/GLM-OCR (GitHub)](https://github.com/zai-org/GLM-OCR)
- [zai-org/GLM-OCR vLLM recipe](https://recipes.vllm.ai/zai-org/GLM-OCR)
- [onnx-community/GLM-OCR-ONNX (HF)](https://huggingface.co/onnx-community/GLM-OCR-ONNX)
- [ollama.com/library/glm-ocr](https://ollama.com/library/glm-ocr)
- [vorojar/Folio-OCR (GitHub, референс GLM-пути)](https://github.com/vorojar/Folio-OCR)
- [HunyuanOCR Technical Report (arXiv 2511.19575)](https://arxiv.org/abs/2511.19575)
- [HunyuanOCR-1.5 (arXiv 2607.04884)](https://arxiv.org/abs/2607.04884)
- [tencent/HunyuanOCR (HF)](https://huggingface.co/tencent/HunyuanOCR)
- [MarkTechPost: Tencent releases HunyuanOCR 1B](https://www.marktechpost.com/2025/11/26/tencent-hunyuan-releases-hunyuanocr-a-1b-parameter-end-to-end-ocr-expert-vlm/)
- [MinerU2.5 (arXiv 2509.22186)](https://arxiv.org/pdf/2509.22186)
- [MinerU2.5-Pro (arXiv 2604.04771)](https://arxiv.org/html/2604.04771v1)
- [opendatalab/MinerU2.5-Pro-2604-1.2B (HF)](https://huggingface.co/opendatalab/MinerU2.5-Pro-2604-1.2B)
- [ibm-granite/granite-docling-258M (HF)](https://huggingface.co/ibm-granite/granite-docling-258M)
- [onnx-community/granite-docling-258M-ONNX](https://huggingface.co/onnx-community/granite-docling-258M-ONNX)
- [granite-docling-258M · ONNX conversion / benchmarks discussion](https://huggingface.co/ibm-granite/granite-docling-258M/discussions/32)
- [granite-docling-258M · "why so slow" discussion](https://huggingface.co/ibm-granite/granite-docling-258M/discussions/37)
- [Spheron: Best Open-Source OCR / Document VLMs to Self-Host 2026](https://www.spheron.network/blog/best-open-source-ocr-vlm-self-host-gpu-cloud-2026/)
- [studio-dots-ai/dots.mocr (GitHub)](https://github.com/studio-dots-ai/dots.mocr)
- [baidu/Unlimited-OCR (HF)](https://huggingface.co/baidu/Unlimited-OCR) · [vLLM recipe](https://recipes.vllm.ai/baidu/Unlimited-OCR) · [arXiv 2606.23050](https://arxiv.org/pdf/2606.23050)
- [HunyuanOCR (GitHub, GGUF/llama.cpp путь)](https://github.com/Tencent-Hunyuan/HunyuanOCR)
- [shamitv/DeepSeek-OCR-CPU (GitHub)](https://github.com/shamitv/DeepSeek-OCR-CPU)
- [deepseek-ai/DeepSeek-OCR · CPU inference fix discussion](https://huggingface.co/deepseek-ai/DeepSeek-OCR/discussions/21)
- [Chandra 2 (Datalab) overview](https://themenonlab.blog/blog/chandra-2-ocr-model-structured-document-extraction)
- [olmOCR 2: Unit Test Rewards (arXiv 2510.19817)](https://arxiv.org/pdf/2510.19817)
- [Azure AI Foundry: Chandra OCR 2 + GLM-OCR](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/now-in-foundry-command-a-w4a4-chandra-ocr-2-and-glm-ocr/4526875)
- [OmniDocBench (CVPR 2025, GitHub)](https://github.com/opendatalab/OmniDocBench)
