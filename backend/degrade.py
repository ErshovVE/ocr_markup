"""
Дефекты печати и сканирования на отрисованной странице PDF (Augraphy) до нарезки строк.

Отдельный слой: страница портится целиком (пятна, тени, неравномерный свет,
просвечивание согласованы по всей странице, как на настоящем скане), потом из
неё режутся строки по боксам текстового слоя. Эффекты только «чернильные»,
«бумажные» и «постпечатные»: геометрию они не меняют, боксы остаются точными;
эффект, изменивший размер страницы, -- GeometryChangedError.

Порча нужна только там, где метка не зависит от пикселей, -- на страницах с
текстовым слоем (backend/pipeline.py::_process_pdf_page). Метка должна совпадать с
нарисованным, поэтому каждая строка сравнивается со своей чистой копией
(legible()): нечитаемая строка берётся с чистой страницы.

Эффекты описываются как данные: {name, p, params} -- класс Augraphy с параметрами,
{one_of: [...], p} -- один из списка. Augraphy импортируется только при включённой
порче: без неё зависимость не нужна.

Предпросмотр страниц:
    python -m backend.degrade --input <pdf|папка> --out <папка> [--page-share 1] [--seed 0]
"""

import argparse
import copy
import json
import os
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

# Пороги legible(). По всей строке: доля пикселей текста, оставшихся текстом, и доля фона,
# ставшего похожим на текст (пятна, полосы поверх букв). То же по окнам шириной в полвысоты
# строки (~буква): стёртое или залитое одно слово длинной строки по всей строке почти не видно.
MIN_INK_KEPT = 0.7
MAX_DARK_BACKGROUND = 0.08
MIN_WINDOW_INK_KEPT = 0.25
MAX_WINDOW_DARK_BACKGROUND = 0.35
# Ниже этой доли контраста чистой строки порог не опускается (бледный текст сам по себе).
MIN_CONTRAST_SHARE = 0.5
# Кроп, где текста или фона меньше стольких пикселей (точка, тире): сравнивается попиксельно.
MIN_INK_PIXELS = 10
MAX_TINY_MEAN_DIFF = 40.0
DEFAULT_MIN_CONTRAST = 25.0
PHASES = ("ink", "paper", "post")
_EFFECT_KEYS = {"name", "p", "params", "one_of"}

# Набор по умолчанию: заметно на строке высотой ~48 px и укладывается в несколько секунд
# на страницу A4/A3 200 dpi. Не взяты: InkShifter и Hollow (4-6 с на страницу), Markup и
# BadPhotoCopy (падают внутри Augraphy/numba), геометрические эффекты.
DEFAULT_EFFECTS: Dict[str, List[Dict[str, Any]]] = {
    "ink": [
        {
            "one_of": [
                {
                    "name": "InkBleed",
                    "params": {
                        "intensity_range": [0.3, 0.6],
                        "kernel_size": [3, 3],
                        "severity": [0.2, 0.4],
                    },
                },
                {
                    "name": "LowInkRandomLines",
                    "params": {"count_range": [5, 30], "use_consistent_lines": False},
                },
                {
                    "name": "LowInkPeriodicLines",
                    "params": {"count_range": [2, 5], "period_range": [16, 48]},
                },
                {"name": "InkMottling"},
            ],
            "p": 0.5,
        },
        {"name": "Letterpress", "p": 0.15},
    ],
    "paper": [
        {
            "one_of": [
                {
                    "name": "NoiseTexturize",
                    "params": {"sigma_range": [3, 10], "turbulence_range": [2, 5]},
                },
                {
                    "name": "BrightnessTexturize",
                    "params": {"texturize_range": [0.9, 0.99], "deviation": 0.03},
                },
            ],
            "p": 0.5,
        },
        {"name": "Stains", "p": 0.1},
    ],
    "post": [
        {
            "one_of": [
                {"name": "DirtyRollers", "params": {"line_width_range": [2, 32]}},
                {
                    "name": "DirtyDrum",
                    "params": {"line_width_range": [1, 3], "noise_intensity": 0.2},
                },
            ],
            "p": 0.2,
        },
        {
            "one_of": [
                {
                    "name": "LightingGradient",
                    "params": {
                        "max_brightness": 255,
                        "min_brightness": 120,
                        "mode": "gaussian",
                        "transparency": 0.3,
                    },
                },
                {"name": "ShadowCast", "params": {"shadow_opacity_range": [0.2, 0.5]}},
            ],
            "p": 0.2,
        },
        {
            "name": "BleedThrough",
            "p": 0.15,
            "params": {"intensity_range": [0.1, 0.2], "alpha": 0.1},
        },
        {"name": "SubtleNoise", "p": 0.3, "params": {"subtle_range": 8}},
        {"name": "Faxify", "p": 0.1, "params": {"scale_range": [0.8, 1.0], "monochrome": 0}},
        {"name": "Gamma", "p": 0.2},
        {"name": "Jpeg", "p": 0.3, "params": {"quality_range": [40, 85]}},
    ],
}


class GeometryChangedError(ValueError):
    """Эффект изменил размер или каналы страницы: боксы строк больше не совпадают с пикселями."""


@dataclass
class DegradeOptions:
    page_share: float = 0.0  # доля испорченных страниц; 0 -- выключено
    seed: int = 0  # сид страницы = (seed, имя файла, номер страницы): повтор прогона портит так же
    min_contrast: float = DEFAULT_MIN_CONTRAST  # см. legible()
    effects: Dict[str, List[Dict[str, Any]]] = field(
        default_factory=lambda: copy.deepcopy(DEFAULT_EFFECTS)
    )

    @property
    def enabled(self) -> bool:
        return self.page_share > 0


# --- описание эффектов --------------------------------------------------------


def spec_errors(spec: Any, where: str) -> List[str]:
    """Ошибки формы описания эффекта (без импорта Augraphy)."""
    if not isinstance(spec, dict):
        return [f"{where}: эффект должен быть словарём, получено {spec!r}"]
    errors = []
    if set(spec) - _EFFECT_KEYS or ("name" in spec) == ("one_of" in spec):
        errors.append(
            f"{where}: нужен ровно один из ключей 'name' или 'one_of' "
            f"(плюс 'p', 'params'): {spec!r}"
        )
    p = spec.get("p", 1.0)
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1:
        errors.append(f"{where}: 'p' должно быть числом от 0 до 1, получено {p!r}")
    if not isinstance(spec.get("params", {}), dict):
        errors.append(f"{where}: 'params' должно быть словарём, получено {spec['params']!r}")
    if "one_of" in spec:
        children = spec["one_of"]
        if not isinstance(children, list) or not children:
            errors.append(f"{where}: 'one_of' должно быть непустым списком, получено {children!r}")
        else:
            for i, child in enumerate(children):
                errors += spec_errors(child, f"{where}.one_of[{i}]")
                if isinstance(child, dict) and "p" in child:
                    errors.append(
                        f"{where}.one_of[{i}]: 'p' у варианта one_of не действует, "
                        "задайте его у one_of"
                    )
    return errors


def effects_errors(effects: Any) -> List[str]:
    """Ошибки всего набора эффектов {ink, paper, post}; при отсутствии ошибок формы эффекты
    собираются (имена классов и параметры Augraphy проверяются до прогона)."""
    if not isinstance(effects, dict) or set(effects) - set(PHASES):
        return [f"эффекты должны быть словарём с ключами из {list(PHASES)}, получено {effects!r}"]
    errors = []
    for phase in PHASES:
        specs = effects.get(phase, [])
        if not isinstance(specs, list):
            errors.append(f"{phase}: должен быть список эффектов, получено {specs!r}")
            continue
        for i, spec in enumerate(specs):
            errors += spec_errors(spec, f"{phase}[{i}]")
    if errors:
        return errors
    try:
        for phase in PHASES:
            for spec in effects.get(phase, []):
                build_effect(spec)
    except ImportError:
        return ["для порчи страниц нужна augraphy (pip install augraphy)"]
    except (TypeError, ValueError) as e:
        return [str(e)]
    return []


def _params(raw: Dict[str, Any]) -> Dict[str, Any]:
    # JSON/YAML дают списки, а Augraphy ждёт кортежи-диапазоны
    return {k: tuple(v) if isinstance(v, list) else v for k, v in raw.items()}


def build_effect(spec: Dict[str, Any]):
    import augraphy

    errors = spec_errors(spec, "эффект")
    if errors:
        raise ValueError("; ".join(errors))
    p = float(spec.get("p", 1.0))
    if "one_of" in spec:
        return augraphy.OneOf([build_effect({**child, "p": 1.0}) for child in spec["one_of"]], p=p)
    cls = getattr(augraphy, spec["name"], None)
    if cls is None:
        raise ValueError(f"нет такого эффекта Augraphy: {spec['name']!r}")
    return cls(p=p, **_params(spec.get("params") or {}))


# --- порча страницы -----------------------------------------------------------


def page_seed(options: DegradeOptions, file_path: str, page_index: int) -> random.Random:
    """Генератор страницы: от сида прогона, имени файла и номера страницы (не от порядка
    обработки), поэтому повторный прогон и прогон части папки портят страницу так же."""
    return random.Random(f"{options.seed}:{os.path.basename(file_path)}:{page_index}")


def maybe_degrade_page(
    image: np.ndarray, options: DegradeOptions, rng: random.Random
) -> Optional[np.ndarray]:
    """Испорченная копия страницы или None, если страница не выпала (доля page_share)."""
    if not options.enabled or rng.random() >= options.page_share:
        return None
    return degrade_page(image, options.effects, rng.getrandbits(32))


def degrade_page(
    image: np.ndarray, effects: Dict[str, List[Dict[str, Any]]], seed: int
) -> np.ndarray:
    """Испорченная копия страницы того же размера и с тем же числом каналов."""
    import augraphy
    import cv2

    # Augraphy берёт случайные числа из глобальных random/np.random/cv2: засеваем их сидом
    # страницы и возвращаем random/np.random остального кода. Повтор побайтный не всегда:
    # у jit-функций numba свой генератор, а BleedThrough берёт «оборот» листа из общего
    # кэша augraphy_cache/ (до 30 последних страниц) в текущей папке.
    py_state, np_state = random.getstate(), np.random.get_state()
    try:
        random.seed(seed)
        np.random.seed(seed)
        cv2.setRNGSeed(seed % 2**31)
        pipeline = augraphy.AugraphyPipeline(  # конструкторы эффектов тоже тянут случайные числа
            **{
                f"{phase}_phase": [build_effect(s) for s in effects.get(phase, [])]
                for phase in PHASES
            }
        )
        out = pipeline(image)
    finally:
        random.setstate(py_state)
        np.random.set_state(np_state)
    if out.ndim == 2 and image.ndim == 3:
        out = np.repeat(out[:, :, None], image.shape[2], axis=2)
    if out.shape != image.shape:
        raise GeometryChangedError(
            f"порча изменила геометрию страницы {image.shape} -> {out.shape}: "
            "допустимы только эффекты, не двигающие пиксели"
        )
    return np.ascontiguousarray(out, dtype=np.uint8)


# --- проверка читаемости строки -----------------------------------------------


def _gray(image: np.ndarray) -> np.ndarray:
    return image.mean(axis=2) if image.ndim == 3 else image.astype(np.float64)


def _ink_mask(gray: np.ndarray) -> np.ndarray:
    """Пиксели текста чистого кропа: меньшинство по одну сторону середины яркости
    (тёмный текст на светлом и светлый на тёмной плашке)."""
    dark = gray < (gray.min() + gray.max()) / 2
    return dark if dark.mean() <= 0.5 else ~dark


def _windows_ok(ink: np.ndarray, like_ink: np.ndarray) -> bool:
    height, width = ink.shape
    step = max(4, height // 2)
    for x in range(0, width, step):
        ink_w, like_w = ink[:, x : x + step], like_ink[:, x : x + step]
        if ink_w.sum() >= MIN_INK_PIXELS and like_w[ink_w].mean() < MIN_WINDOW_INK_KEPT:
            return False  # слово стёрто или выцвело
        if (~ink_w).sum() >= MIN_INK_PIXELS and like_w[~ink_w].mean() > MAX_WINDOW_DARK_BACKGROUND:
            return False  # пятно или полоса поверх букв
    return True


def legible(
    clean: np.ndarray, noisy: np.ndarray, min_contrast: float = DEFAULT_MIN_CONTRAST
) -> bool:
    """Читается ли строка после порчи так же, как до неё.

    Пиксели текста берутся с чистого кропа. На испорченном: контраст текст/фон не меньше
    min_contrast (для бледного текста -- не меньше половины его собственного); почти весь
    текст остался текстом, а фон почти нигде не стал похож на текст -- по всей строке и в
    каждом окне шириной около буквы. Кроп почти без текста или без фона (точка, тире)
    должен остаться близким к чистому попиксельно."""
    g_clean, g_noisy = _gray(clean), _gray(noisy)
    ink = _ink_mask(g_clean)
    if ink.sum() < MIN_INK_PIXELS or (~ink).sum() < MIN_INK_PIXELS:
        return bool(np.abs(g_noisy - g_clean).mean() <= MAX_TINY_MEAN_DIFF)
    sign = 1.0 if np.median(g_clean[~ink]) >= np.median(g_clean[ink]) else -1.0  # тёмный текст: +1
    clean_contrast = sign * (np.median(g_clean[~ink]) - np.median(g_clean[ink]))
    bg, fg = np.median(g_noisy[~ink]), np.median(g_noisy[ink])
    if sign * (bg - fg) < min(min_contrast, MIN_CONTRAST_SHARE * clean_contrast):
        return False
    like_ink = sign * (g_noisy - (bg + fg) / 2) < 0  # по ту же сторону порога, что текст
    if like_ink[ink].mean() < MIN_INK_KEPT or like_ink[~ink].mean() > MAX_DARK_BACKGROUND:
        return False
    return _windows_ok(ink, like_ink)


def choose_crop(
    clean: np.ndarray, noisy: Optional[np.ndarray], min_contrast: float
) -> Optional[bool]:
    """Какой кроп строки брать: True -- испорченный, False -- чистый (порча сделала строку
    нечитаемой), None -- страница не портилась или эффекты строку не задели."""
    if noisy is None or np.array_equal(noisy, clean):
        return None
    return legible(clean, noisy, min_contrast)


# --- предпросмотр страниц -----------------------------------------------------


def _pdf_files(path: str) -> List[str]:
    if os.path.isfile(path):
        return [path]
    return sorted(os.path.join(path, n) for n in os.listdir(path) if n.lower().endswith(".pdf"))


def preview(input_path: str, out_dir: str, options: DegradeOptions, dpi: int) -> int:
    """Рендерит страницы PDF, портит долю page_share и пишет страницы в WebP без потерь
    (как кропы pipeline) + pages.jsonl (файл, страница, испорчена ли). Возвращает число
    записанных страниц."""
    import cv2
    import pypdfium2 as pdfium

    from backend import pdf_extract

    os.makedirs(out_dir, exist_ok=True)
    written = 0
    with open(os.path.join(out_dir, "pages.jsonl"), "w", encoding="utf-8") as log:
        for file_path in _pdf_files(input_path):
            doc = pdfium.PdfDocument(file_path)
            try:
                for page_index in range(len(doc)):
                    page = doc[page_index]
                    try:
                        image = pdf_extract.render_page(page, dpi=dpi)
                    finally:
                        page.close()
                    noisy = maybe_degrade_page(
                        image, options, page_seed(options, file_path, page_index)
                    )
                    stem = os.path.splitext(os.path.basename(file_path))[0]
                    name = f"{stem}_p{page_index + 1:03d}.webp"
                    shown = image if noisy is None else noisy
                    cv2.imwrite(
                        os.path.join(out_dir, name),
                        cv2.cvtColor(shown, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_WEBP_QUALITY, 101],  # 101 -- без потерь
                    )
                    log.write(
                        json.dumps(
                            {
                                "file": file_path,
                                "page": page_index + 1,
                                "image": name,
                                "degraded": noisy is not None,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    written += 1
            finally:
                doc.close()
    return written


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Предпросмотр порчи страниц PDF (Augraphy)")
    parser.add_argument("--input", required=True, help="PDF или папка с PDF")
    parser.add_argument("--out", required=True, help="куда писать страницы (WebP) и pages.jsonl")
    parser.add_argument(
        "--page-share", type=float, default=1.0, help="доля испорченных страниц (0..1)"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--effects", help="JSON-файл с набором эффектов {ink, paper, post}")
    args = parser.parse_args(argv)

    options = DegradeOptions(page_share=args.page_share, seed=args.seed)
    if args.effects:
        with open(args.effects, encoding="utf-8") as f:
            options.effects = json.load(f)
    errors = effects_errors(options.effects)
    if not 0 <= options.page_share <= 1:
        errors.append(f"--page-share должно быть от 0 до 1, получено {options.page_share}")
    if errors:
        parser.error("; ".join(errors))
    written = preview(args.input, args.out, options, args.dpi)
    print(f"записано страниц: {written} -> {args.out}")


if __name__ == "__main__":
    main()
