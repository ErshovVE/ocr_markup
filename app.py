import streamlit as st
import os
import shutil
from PIL import Image

st.set_page_config(layout="wide")


@st.cache_data
def load_and_resize_image(image_path, max_height=100, max_width=1000):
    """Загружает и изменяет размер изображения, кешируя результат."""
    try:
        image = Image.open(image_path).convert("RGB")
        original_width, original_height = image.size

        height_ratio = max_height / original_height
        width_ratio = max_width / original_width
        scale = min(height_ratio, width_ratio)

        new_width = int(original_width * scale)
        new_height = int(original_height * scale)

        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        return image

    except (FileNotFoundError, IOError) as e:
        st.error(f"Ошибка загрузки или изменения размера изображения {image_path}: {e}")
        return None, None


def get_status_cache_path(image_base_directory: str, relative_paths: list) -> str:
    """
    Определяет путь к файлу кэша статусов на основе первой относительной директории.
    Например, если путь myplace/images/0/image_00005.webp, то кэш будет в G:/Датасет/myplace/status_cache.txt
    """
    if not relative_paths:
        # Если нет путей, используем базовую директорию
        return os.path.join(image_base_directory, "status_cache.txt")

    # Берем первый относительный путь и извлекаем первую директорию
    first_relative_path = relative_paths[0]
    # Разделяем путь на части
    path_parts = first_relative_path.replace("\\", "/").split("/")
    if path_parts and path_parts[0]:
        first_dir = path_parts[0]
        # Путь к кэшу: базовая_директория/первая_директория/status_cache.txt
        cache_dir = os.path.join(image_base_directory, first_dir)
        return os.path.join(cache_dir, "status_cache.txt")
    else:
        # Если не удалось определить первую директорию, используем базовую
        return os.path.join(image_base_directory, "status_cache.txt")


@st.cache_data
def load_annotation_data(
    file_contents: str,
    image_base_directory: str,
    working_dir_for_cache: str,  # working_dir_for_cache оставлен для совместимости, но не используется
):
    """Загружает данные разметки из содержимого файла, разрешает пути и инициализирует статусы."""
    annotations = {}
    image_files = []  # Абсолютные пути
    original_relative_paths_for_saving = []  # Относительные пути для сохранения
    status_icons = {}
    cached_marked_images = set()

    try:
        lines = file_contents.splitlines()

        image_data_for_processing = []
        image_extensions = (
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".tiff",
            ".webp",
        )  # Допустимые расширения изображений

        for line in lines:
            parts = line.split("\t", 1)
            relative_path_from_line = parts[0].strip()
            annotation_text_from_file = parts[1].strip() if len(parts) == 2 else ""

            absolute_resolved_path = os.path.normpath(
                os.path.join(image_base_directory, relative_path_from_line)
            )

            # Добавляем проверку на существование файла и его расширение
            if os.path.exists(
                absolute_resolved_path
            ) and absolute_resolved_path.lower().endswith(image_extensions):
                image_data_for_processing.append(
                    {
                        "relative_path": relative_path_from_line,
                        "absolute_path": absolute_resolved_path,
                        "annotation": annotation_text_from_file,
                    }
                )
                annotations[os.path.basename(absolute_resolved_path)] = (
                    annotation_text_from_file
                )

        if not image_data_for_processing:
            return (
                annotations,
                image_files,
                original_relative_paths_for_saving,
                status_icons,
                cached_marked_images,
                "Не удалось найти файлы изображений, указанные в файле разметки, или файл пуст.",
            )

        image_files = [data["absolute_path"] for data in image_data_for_processing]
        original_relative_paths_for_saving = [
            data["relative_path"] for data in image_data_for_processing
        ]

        # Загрузка кэша статусов из первой относительной директории
        # ВАЖНО: Используем правильный путь к кэшу на основе первой относительной директории
        status_cache_file_path = get_status_cache_path(
            image_base_directory, original_relative_paths_for_saving
        )
        if os.path.exists(status_cache_file_path):
            try:
                with open(status_cache_file_path, "r", encoding="utf-8") as f:
                    cache_lines = f.read().splitlines()
                    # Убираем пустые строки
                    cached_marked_images = set(
                        line.strip() for line in cache_lines if line.strip()
                    )
            except (IOError, OSError):
                # Если не удалось прочитать кэш, продолжаем без него
                cached_marked_images = set()

        # Инициализация status_icons
        for full_path in image_files:
            img_name = os.path.basename(full_path)
            if img_name in cached_marked_images:
                status_icons[img_name] = "✅"
            elif img_name not in annotations:
                status_icons[img_name] = "❌"
            else:
                status_icons[img_name] = "❓"

        return (
            annotations,
            image_files,
            original_relative_paths_for_saving,
            status_icons,
            cached_marked_images,
            None,
        )

    except (IOError, ValueError) as e:
        return {}, [], [], {}, set(), f"Ошибка при загрузке данных аннотации: {e}"


def delete_current_image():
    """
    Удаляет текущее изображение из файловой системы, из кэша статусов,
    из данных сессии Streamlit и из файла аннотаций.
    """
    if "current_image_idx" not in st.session_state or not st.session_state.image_files:
        st.error("Нет изображений для удаления.")
        return

    current_idx = st.session_state.current_image_idx
    current_full_image_path = st.session_state.image_files[current_idx]
    current_image_name = os.path.basename(current_full_image_path)

    # 1. Удаление изображения из файловой системы
    try:
        os.remove(current_full_image_path)
        st.success(f"Изображение {current_image_name} удалено из файловой системы.")
    except OSError as e:
        st.error(f"Ошибка при удалении файла изображения {current_image_name}: {e}")
        return

    # 2. Удаление из кэша статусов
    if current_image_name in st.session_state.cached_marked_images:
        st.session_state.cached_marked_images.remove(current_image_name)
        # Используем сохраненный путь к кэшу или вычисляем заново
        if "status_cache_path" in st.session_state:
            status_cache_file_path = st.session_state.status_cache_path
        else:
            status_cache_file_path = get_status_cache_path(
                st.session_state.image_base_directory,
                st.session_state.original_relative_paths_for_saving,
            )
        os.makedirs(os.path.dirname(status_cache_file_path), exist_ok=True)
        with open(status_cache_file_path, "w", encoding="utf-8") as f:
            for img_name in st.session_state.cached_marked_images:
                f.write(f"{img_name}\n")
        st.info(f"Изображение {current_image_name} удалено из кэша статусов.")

    # 3. Удаление из данных сессии Streamlit
    st.session_state.image_files.pop(current_idx)
    st.session_state.original_relative_paths_for_saving.pop(current_idx)
    if current_image_name in st.session_state.annotations:
        del st.session_state.annotations[current_image_name]
    if current_image_name in st.session_state.status_icons:
        del st.session_state.status_icons[current_image_name]

    # 4. Обновление файла аннотаций
    # Определяем путь к исходному файлу в рабочей директории
    if "original_annotation_file_name" in st.session_state:
        # Сохраняем в исходный файл в рабочей директории
        original_file_name = st.session_state.original_annotation_file_name
        annotation_file_path = os.path.join(
            st.session_state.image_base_directory, original_file_name
        )
    else:
        # Fallback на временный файл, если имя не сохранено
        annotation_file_path = st.session_state.annotation_file_path

    try:
        with open(annotation_file_path, "w", encoding="utf-8") as f:
            for (
                relative_path_for_saving
            ) in st.session_state.original_relative_paths_for_saving:
                # Восстанавливаем img_name_for_saving из относительного пути для получения аннотации
                full_path_for_saving = os.path.normpath(
                    os.path.join(
                        st.session_state.image_base_directory, relative_path_for_saving
                    )
                )
                img_name_for_saving = os.path.basename(full_path_for_saving)
                annotation_text_to_save = st.session_state.annotations.get(
                    img_name_for_saving, ""
                )
                f.write(f"{relative_path_for_saving}\t{annotation_text_to_save}\n")

        # Проверяем, что файл действительно был обновлен
        if not os.path.exists(annotation_file_path):
            st.error(f"Ошибка: файл {annotation_file_path} не был обновлен.")
        else:
            st.info(f"Файл аннотаций обновлен после удаления {current_image_name}.")
    except (IOError, OSError) as e:
        st.error(f"Ошибка при обновлении файла аннотаций: {e}")

    # Обновление индекса текущего изображения
    if st.session_state.current_image_idx >= len(st.session_state.image_files):
        st.session_state.current_image_idx = max(
            0, len(st.session_state.image_files) - 1
        )

    load_annotation_data.clear()  # Очищаем кэш для принудительной перезагрузки данных
    st.rerun()


def rotate_current_image(direction: str):
    """
    Поворачивает текущее изображение на 90 градусов в указанном направлении (left/right)
    и сохраняет его, обновляя сессию Streamlit.
    """
    if "current_image_idx" not in st.session_state or not st.session_state.image_files:
        st.error("Нет изображений для поворота.")
        return

    current_idx = st.session_state.current_image_idx
    current_full_image_path = st.session_state.image_files[current_idx]
    current_image_name = os.path.basename(current_full_image_path)

    try:
        image = Image.open(current_full_image_path)
        if direction == "right":
            rotated_image = image.rotate(-90, expand=True)  # Поворот вправо
        elif direction == "left":
            rotated_image = image.rotate(90, expand=True)  # Поворот влево
        else:
            st.error("Неверное направление поворота. Используйте 'left' или 'right'.")
            return

        # Сохраняем повернутое изображение, перезаписывая оригинал
        rotated_image.save(current_full_image_path)
        st.success(
            f"Изображение {current_image_name} повернуто {direction} и сохранено."
        )

        # Очищаем кэш для load_and_resize_image, чтобы новое изображение загрузилось
        load_and_resize_image.clear()
        st.rerun()

    except (IOError, FileNotFoundError) as e:
        st.error(f"Ошибка при повороте изображения {current_image_name}: {e}")


def main():
    # CSS для более компактного интерфейса и уменьшения заголовка
    custom_css = """
        <style>
        [data-testid="stToolbar"] {visibility: hidden;}
        [data-testid="stDecoration"] {visibility: hidden;}
        [data-testid="stStatusWidget"] {visibility: hidden;}
        header {visibility: hidden;}
        .block-container {padding-top: 1rem; padding-bottom: 1rem;}

        /* Стили для рамки вокруг изображения */
        img {
            border: 2px solid blue;
            box-shadow: 2px 2px 5px rgba(0, 0, 0, 0.2);
        }

        </style>
    """
    st.markdown(custom_css, unsafe_allow_html=True)

    st.title("Инструмент разметки OCR")

    if "annotation_file_path" not in st.session_state:
        st.session_state.annotation_file_path = ""

    # Заменяем st.text_input на st.file_uploader
    uploaded_annotation_file = st.file_uploader("Загрузите файл разметки", type=["txt"])

    # Обработка загрузки нового файла
    if uploaded_annotation_file is not None:
        # Сохраняем имя исходного файла
        original_file_name = uploaded_annotation_file.name
        st.session_state.original_annotation_file_name = original_file_name

        # Читаем содержимое файла (не сохраняем во временную папку)
        file_contents = uploaded_annotation_file.read().decode("utf-8")

        # Сохраняем содержимое файла в session_state для дальнейшей обработки
        st.session_state.annotation_file_contents = file_contents

        # Добавляем поле для ввода базовой директории изображений
        if "image_base_directory" not in st.session_state:
            st.session_state.image_base_directory = ""
        image_base_directory = st.text_input(
            "Укажите рабочую директорию",
            value=st.session_state.image_base_directory,
        )
        # Сохраняем введённое значение в session_state, чтобы использовать его в других функциях
        st.session_state.image_base_directory = image_base_directory

        if not image_base_directory:
            st.warning("Пожалуйста, укажите рабочую директорию.")
            return
        if not os.path.isdir(image_base_directory):
            st.error("Указанная рабочая директория не существует.")
            return

        # Вызываем кэшированную функцию для загрузки всех данных
        # working_dir_for_cache больше не используется, путь к кэшу определяется автоматически
        (
            annotations,
            image_files,
            original_relative_paths_for_saving,
            status_icons,
            cached_marked_images,
            error_message,
        ) = load_annotation_data(
            file_contents,
            image_base_directory,
            image_base_directory,  # Передаем базовую директорию, путь к кэшу определяется внутри функции
        )

        # Сохраняем путь к кэшу статусов для дальнейшего использования
        if original_relative_paths_for_saving:
            st.session_state.status_cache_path = get_status_cache_path(
                image_base_directory, original_relative_paths_for_saving
            )
        else:
            st.session_state.status_cache_path = os.path.join(
                image_base_directory, "status_cache.txt"
            )

        if error_message:
            st.error(error_message)
            return

        if not image_files:
            st.warning(
                "В файле разметки не найдено существующих изображений с допустимыми расширениями."
            )
            return

        st.session_state.annotations = annotations
        st.session_state.image_files = image_files
        st.session_state.original_relative_paths_for_saving = (
            original_relative_paths_for_saving
        )
        st.session_state.status_icons = status_icons
        st.session_state.cached_marked_images = cached_marked_images

        if "current_image_idx" not in st.session_state:
            st.session_state.current_image_idx = 0

        # Обновляем last_* для кэширования
        st.session_state.last_annotation_file_path = (
            st.session_state.annotation_file_path
        )
        st.session_state.last_image_files = st.session_state.image_files
        st.session_state.last_image_base_directory = image_base_directory

        # Инициализация пагинации
        if "page_size" not in st.session_state:
            st.session_state.page_size = 100  # Количество изображений на странице
        if "current_page" not in st.session_state:
            st.session_state.current_page = 0

        # Убедимся, что current_image_idx соответствует current_page
        if st.session_state.current_image_idx not in range(
            st.session_state.current_page * st.session_state.page_size,
            (st.session_state.current_page + 1) * st.session_state.page_size,
        ):
            st.session_state.current_page = (
                st.session_state.current_image_idx // st.session_state.page_size
            )

    # Обработка случая, когда файл уже загружен (работа с существующими данными)
    elif (
        "annotation_file_path" in st.session_state
        and st.session_state.annotation_file_path
        and os.path.exists(st.session_state.annotation_file_path)
    ):
        # Файл уже загружен, продолжаем работу с существующими данными
        # Обновляем рабочую директорию, если она не установлена
        if "working_dir" not in st.session_state:
            st.session_state.working_dir = os.path.dirname(
                st.session_state.annotation_file_path
            )

        # Поле для ввода базовой директории изображений (если еще не установлено)
        if "image_base_directory" not in st.session_state:
            st.session_state.image_base_directory = ""
        image_base_directory = st.text_input(
            "Укажите рабочую директорию",
            value=st.session_state.image_base_directory,
        )
        # Сохраняем введённое значение в session_state
        st.session_state.image_base_directory = image_base_directory

        if not image_base_directory:
            st.warning("Пожалуйста, укажите рабочую директорию.")
            return
        if not os.path.isdir(image_base_directory):
            st.error("Указанная рабочая директория не существует.")
            return

        # Перезагружаем данные из файла, если они изменились (например, после удаления)
        # Читаем текущее содержимое файла
        try:
            with open(
                st.session_state.annotation_file_path, "r", encoding="utf-8"
            ) as f:
                current_file_contents = f.read()

            # Загружаем данные из текущего файла
            (
                annotations,
                image_files,
                original_relative_paths_for_saving,
                status_icons,
                cached_marked_images,
                error_message,
            ) = load_annotation_data(
                current_file_contents,
                image_base_directory,
                image_base_directory,  # working_dir_for_cache больше не используется
            )

            # Сохраняем путь к кэшу статусов для дальнейшего использования
            if original_relative_paths_for_saving:
                st.session_state.status_cache_path = get_status_cache_path(
                    image_base_directory, original_relative_paths_for_saving
                )
            else:
                st.session_state.status_cache_path = os.path.join(
                    image_base_directory, "status_cache.txt"
                )

            if error_message:
                st.error(error_message)
                return

            # Обновляем session_state только если списки изменились (например, после удаления)
            # ИЛИ если annotations изменились (например, после сохранения)
            lists_changed = (
                "image_files" not in st.session_state
                or len(st.session_state.image_files) != len(image_files)
                or st.session_state.image_files != image_files
            )

            # Проверяем, изменились ли annotations (сравниваем ключи и значения)
            annotations_changed = False
            if "annotations" in st.session_state:
                # Проверяем, есть ли различия в ключах или значениях
                if set(st.session_state.annotations.keys()) != set(annotations.keys()):
                    annotations_changed = True
                else:
                    # Проверяем значения для текущего изображения
                    for key in annotations:
                        if st.session_state.annotations.get(key, "") != annotations.get(
                            key, ""
                        ):
                            annotations_changed = True
                            break
            else:
                annotations_changed = True

            if lists_changed or annotations_changed:
                # Обновляем все данные из файла
                st.session_state.annotations = annotations
                st.session_state.image_files = image_files
                st.session_state.original_relative_paths_for_saving = (
                    original_relative_paths_for_saving
                )

                # Обновляем status_icons из загруженных данных (включая статусы из кэша)
                # ВАЖНО: status_icons уже содержит правильные статусы из кэша, загруженного из правильного места
                st.session_state.status_icons = status_icons.copy()
                st.session_state.cached_marked_images = cached_marked_images

                # Корректируем current_image_idx, если он вышел за границы
                if "current_image_idx" in st.session_state:
                    if st.session_state.current_image_idx >= len(image_files):
                        st.session_state.current_image_idx = max(
                            0, len(image_files) - 1
                        )
                else:
                    st.session_state.current_image_idx = 0

            # Инициализация пагинации
            if "page_size" not in st.session_state:
                st.session_state.page_size = 100
            if "current_page" not in st.session_state:
                st.session_state.current_page = 0

            # Убедимся, что current_image_idx соответствует current_page
            if st.session_state.current_image_idx not in range(
                st.session_state.current_page * st.session_state.page_size,
                (st.session_state.current_page + 1) * st.session_state.page_size,
            ):
                st.session_state.current_page = (
                    st.session_state.current_image_idx // st.session_state.page_size
                )
        except (IOError, FileNotFoundError) as e:
            st.error(f"Ошибка при чтении файла аннотаций: {e}")
            return

    else:
        st.warning("Пожалуйста, загрузите файл разметки.")
        return

    # Отображение основной части приложения только если файл разметки загружен и есть изображения
    if "image_files" in st.session_state and st.session_state.image_files:
        if "filter_option" not in st.session_state:
            st.session_state.filter_option = "Все изображения"

        # Отфильтровываем изображения в зависимости от выбранной опции
        if st.session_state.filter_option == "Только неразмеченные":
            display_image_files = [
                f_path
                for f_path in st.session_state.image_files
                if st.session_state.status_icons.get(os.path.basename(f_path), "❌")
                != "✅"
            ]
        elif st.session_state.filter_option == "Только размеченные":
            display_image_files = [
                f_path
                for f_path in st.session_state.image_files
                if st.session_state.status_icons.get(os.path.basename(f_path), "❌")
                == "✅"
            ]
        else:  # "Все изображения"
            display_image_files = st.session_state.image_files

        total_images = len(display_image_files)
        total_pages = (
            total_images + st.session_state.page_size - 1
        ) // st.session_state.page_size

        # Если изображений нет после фильтрации, выводим предупреждение и завершаем отображение этой части UI
        if total_images == 0:
            st.warning("Нет изображений для разметки по текущему фильтру.")
            # Сбрасываем current_image_idx, если он неактуален
            st.session_state.current_image_idx = 0
            # Здесь мы не возвращаемся из main(), чтобы остальная часть приложения (загрузка файла) работала.
            # Вместо этого, мы просто не рендерим col1 и col2.
        else:  # Только если есть изображения, создаем колонки и рендерим их содержимое
            # Дополнительная защита: убеждаемся, что current_image_idx находится в допустимых пределах
            if st.session_state.current_image_idx < 0:
                st.session_state.current_image_idx = 0
            if st.session_state.current_image_idx >= len(st.session_state.image_files):
                st.session_state.current_image_idx = (
                    len(st.session_state.image_files) - 1
                )

            # Если текущая страница или индекс изображения выходят за пределы нового отфильтрованного списка
            if st.session_state.current_page >= total_pages:
                st.session_state.current_page = (
                    total_pages - 1 if total_pages > 0 else 0
                )

            # Убедимся, что current_image_idx указывает на действительное изображение в ОТФИЛЬТРОВАННОМ списке
            # и что оно находится на текущей странице.
            # Сначала найдем текущий original_index_in_full_list в display_image_files.
            try:
                current_image_file = st.session_state.image_files[
                    st.session_state.current_image_idx
                ]
                if current_image_file in display_image_files:
                    current_global_idx_in_filtered = display_image_files.index(
                        current_image_file
                    )
                    # Если текущий global_idx_in_filtered не на текущей странице, перейдем на страницу этого изображения
                    expected_page_for_current_image = (
                        current_global_idx_in_filtered // st.session_state.page_size
                    )
                    if st.session_state.current_page != expected_page_for_current_image:
                        st.session_state.current_page = expected_page_for_current_image
                else:
                    # текущее изображение не найдено в отфильтрованном списке
                    st.session_state.current_image_idx = (
                        st.session_state.image_files.index(display_image_files[0])
                    )  # Переходим к первому изображению в отфильтрованном списке
                    st.session_state.current_page = 0
                    st.rerun()  # Нужно перезапустить, чтобы обновить UI
            except IndexError:
                # Защита от редких гонок состояний: откатываемся к первому изображению
                st.session_state.current_image_idx = 0
                st.session_state.current_page = 0
                st.rerun()

            start_index = st.session_state.current_page * st.session_state.page_size
            end_index = min(start_index + st.session_state.page_size, total_images)

            col1, col2 = st.columns([1, 2])

            with col1:
                st.subheader("Список изображений")

                def on_filter_change():
                    st.session_state.current_page = 0
                    new_filter_option = st.session_state.filter_radio
                    st.session_state.filter_option = new_filter_option

                    # Временно вычисляем новый отфильтрованный список, чтобы найти первое изображение
                    if new_filter_option == "Только неразмеченные":
                        temp_display_image_files = [
                            f_path
                            for f_path in st.session_state.image_files
                            if st.session_state.status_icons.get(
                                os.path.basename(f_path), "❌"
                            )
                            != "✅"
                        ]
                    elif new_filter_option == "Только размеченные":
                        temp_display_image_files = [
                            f_path
                            for f_path in st.session_state.image_files
                            if st.session_state.status_icons.get(
                                os.path.basename(f_path), "❌"
                            )
                            == "✅"
                        ]
                    else:  # "Все изображения"
                        temp_display_image_files = st.session_state.image_files

                    if temp_display_image_files:
                        # Устанавливаем current_image_idx на оригинальный индекс первого изображения в новом отфильтрованном списке
                        st.session_state.current_image_idx = (
                            st.session_state.image_files.index(
                                temp_display_image_files[0]
                            )
                        )
                    else:
                        # Если нет изображений по новому фильтру, сбросим current_image_idx в 0
                        st.session_state.current_image_idx = 0

                    st.rerun()

                st.radio(
                    "Показать:",
                    ("Все изображения", "Только неразмеченные", "Только размеченные"),
                    key="filter_radio",
                    index=(
                        (
                            "Все изображения",
                            "Только неразмеченные",
                            "Только размеченные",
                        ).index(st.session_state.filter_option)
                    ),
                    on_change=on_filter_change,
                )

                # Список изображений
                with st.container(height=400):
                    # Используем display_image_files для отображения
                    for full_path in display_image_files[start_index:end_index]:
                        original_index_in_full_list = (
                            st.session_state.image_files.index(full_path)
                        )
                        img_name = os.path.basename(full_path)
                        status_icon = st.session_state.status_icons.get(img_name, "❌")
                        display_name = f"{status_icon} {img_name}"

                        # Отмечаем текущее изображение в списке. current_image_idx должен соответствовать оригинальному индексу.
                        if (
                            original_index_in_full_list
                            == st.session_state.current_image_idx
                        ):
                            st.markdown(f"**-> {display_name}**")
                        else:
                            if st.button(
                                display_name,
                                key=f"img_select_{original_index_in_full_list}",
                            ):
                                st.session_state.current_image_idx = (
                                    original_index_in_full_list
                                )
                                st.session_state.current_page = (
                                    original_index_in_full_list
                                    // st.session_state.page_size
                                )  # Корректируем страницу
                                st.rerun()

                # Кнопки пагинации (создаются только если total_images > 0)
                prev_page_col, page_info_col, next_page_col = st.columns([1, 2, 1])
                with prev_page_col:
                    if st.button(
                        "← Предыдущая страница",
                        disabled=(st.session_state.current_page == 0),
                        key="prev_page_button",
                    ):
                        st.session_state.current_page -= 1
                        # Убедимся, что current_image_idx соответствует первой картинке на новой странице в отфильтрованном списке
                        # и найдем ее реальный индекс в st.session_state.image_files
                        first_image_on_page_path = display_image_files[
                            st.session_state.current_page * st.session_state.page_size
                        ]
                        st.session_state.current_image_idx = (
                            st.session_state.image_files.index(first_image_on_page_path)
                        )
                        st.rerun()
                with page_info_col:
                    st.markdown(
                        f"Страница {st.session_state.current_page + 1} из {total_pages}"
                    )
                with next_page_col:
                    if st.button(
                        "Следующая страница →",
                        disabled=(st.session_state.current_page == total_pages - 1),
                        key="next_page_button",
                    ):
                        st.session_state.current_page += 1
                        # Убедимся, что current_image_idx соответствует первой картинке на новой странице в отфильтрованном списке
                        # и найдем ее реальный индекс в st.session_state.image_files
                        first_image_on_page_path = display_image_files[
                            st.session_state.current_page * st.session_state.page_size
                        ]
                        st.session_state.current_image_idx = (
                            st.session_state.image_files.index(first_image_on_page_path)
                        )
                        st.rerun()

            with col2:
                # Получаем текущее изображение из оригинального списка
                current_full_image_path = st.session_state.image_files[
                    st.session_state.current_image_idx
                ]
                # Получаем относительный путь для текущего изображения
                current_relative_path = (
                    st.session_state.original_relative_paths_for_saving[
                        st.session_state.current_image_idx
                    ]
                )

                # Вычисляем имя файла единообразно - из относительного пути (как при сохранении)
                current_image_name = os.path.basename(
                    os.path.normpath(
                        os.path.join(
                            st.session_state.image_base_directory,
                            current_relative_path,
                        )
                    )
                )
                st.subheader(f"Текущее изображение: {current_image_name}")

                # st3 = time.time() # Удаляем таймер
                try:
                    image = load_and_resize_image(
                        current_full_image_path, max_height=80, max_width=1200
                    )
                    if image:
                        st.image(image)
                except (FileNotFoundError, IOError) as e:
                    st.error(
                        f"Ошибка при загрузке изображения {current_image_name}: {e}"
                    )

                default_text = st.session_state.annotations.get(current_image_name, "")

                # Используем session_state для хранения текста аннотации
                annotation_key = f"annotation_text_{current_image_name}"
                if annotation_key not in st.session_state:
                    st.session_state[annotation_key] = default_text

                with st.form(key=f"annotation_form_{current_image_name}"):
                    text_input_value = st.text_input(
                        "Текст с изображения",
                        value=st.session_state.get(annotation_key, default_text),
                        key=f"text_input_form_{current_image_name}",
                    )
                    # Обработка переносов строки - замена на пробелы
                    text_input_value = text_input_value.replace("\n", " ").replace(
                        "\r", " "
                    )
                    # Сохраняем значение в session_state сразу
                    st.session_state[annotation_key] = text_input_value

                    col_form1, col_form2 = st.columns([1, 1])
                    with col_form1:
                        submit_button = st.form_submit_button("Подтвердить")
                    with col_form2:
                        handwritten_button = st.form_submit_button("Рукописный текст")

                    # Обработка основного подтверждения разметки
                    if submit_button:
                        # Используем значение из session_state, которое гарантированно актуально
                        annotation_text = st.session_state[annotation_key].strip()

                        # ВАЖНО: Сначала обновляем session_state
                        st.session_state.annotations[current_image_name] = (
                            annotation_text
                        )
                        st.session_state.status_icons[current_image_name] = (
                            "✅"  # Отмечаем как размеченное зеленой галочкой
                        )

                        # Обновляем кэш отмеченных изображений (храним basename)
                        # Убеждаемся, что имя файла совпадает с тем, что используется при загрузке
                        st.session_state.cached_marked_images.add(current_image_name)
                        # Используем сохраненный путь к кэшу или вычисляем заново
                        if "status_cache_path" in st.session_state:
                            status_cache_file_path = st.session_state.status_cache_path
                        else:
                            status_cache_file_path = get_status_cache_path(
                                st.session_state.image_base_directory,
                                st.session_state.original_relative_paths_for_saving,
                            )
                        # Создаем директорию для кэша, если её нет
                        os.makedirs(
                            os.path.dirname(status_cache_file_path), exist_ok=True
                        )
                        try:
                            # Записываем кэш, удаляя пустые строки
                            with open(
                                status_cache_file_path, "w", encoding="utf-8"
                            ) as f:
                                for img_name in sorted(
                                    st.session_state.cached_marked_images
                                ):
                                    if img_name.strip():  # Пропускаем пустые строки
                                        f.write(f"{img_name.strip()}\n")

                            # Проверяем, что файл был записан и содержит текущее изображение
                            if os.path.exists(status_cache_file_path):
                                with open(
                                    status_cache_file_path, "r", encoding="utf-8"
                                ) as f:
                                    cache_content = f.read()
                                if current_image_name in cache_content:
                                    # Очищаем кэш load_annotation_data, чтобы при следующей загрузке
                                    # статусы загрузились из правильного места
                                    load_annotation_data.clear()
                                    st.info(
                                        f"Статус для {current_image_name} сохранен в {status_cache_file_path}"
                                    )
                                else:
                                    st.warning(
                                        f"Предупреждение: {current_image_name} не найден в кэше после записи."
                                    )
                            else:
                                st.error(
                                    f"Ошибка: файл кэша {status_cache_file_path} не был создан."
                                )
                        except (IOError, OSError) as e:
                            st.error(f"Ошибка при сохранении кэша статусов: {e}")

                        # Сохраняем данные разметки в файл аннотаций после каждого подтверждения (храним относительный путь)
                        # Определяем путь к исходному файлу в рабочей директории
                        if "original_annotation_file_name" in st.session_state:
                            # Сохраняем в исходный файл в рабочей директории
                            original_file_name = (
                                st.session_state.original_annotation_file_name
                            )
                            annotation_file_path = os.path.join(
                                st.session_state.image_base_directory,
                                original_file_name,
                            )
                        else:
                            # Fallback на временный файл, если имя не сохранено
                            annotation_file_path = st.session_state.annotation_file_path

                        try:
                            # Создаем список строк для записи
                            lines_to_write = []
                            for (
                                relative_path_for_saving
                            ) in st.session_state.original_relative_paths_for_saving:
                                img_name_for_file = os.path.basename(
                                    os.path.normpath(
                                        os.path.join(
                                            st.session_state.image_base_directory,
                                            relative_path_for_saving,
                                        )
                                    )
                                )
                                annotation_text_to_save = (
                                    st.session_state.annotations.get(
                                        img_name_for_file, ""
                                    )
                                )
                                lines_to_write.append(
                                    f"{relative_path_for_saving}\t{annotation_text_to_save}\n"
                                )

                            # Записываем все строки в файл
                            with open(annotation_file_path, "w", encoding="utf-8") as f:
                                f.writelines(lines_to_write)

                            # Проверяем, что файл действительно был записан и содержит данные
                            if not os.path.exists(annotation_file_path):
                                st.error(
                                    f"Ошибка: файл {annotation_file_path} не был создан."
                                )
                            else:
                                # Проверяем содержимое файла
                                with open(
                                    annotation_file_path, "r", encoding="utf-8"
                                ) as f:
                                    file_content = f.read()
                                # Проверяем, что данные действительно записались
                                # Ищем строку с текущим относительным путем и проверяем аннотацию
                                found_correct_data = False
                                for line in file_content.splitlines():
                                    if line.startswith(current_relative_path + "\t"):
                                        saved_annotation = (
                                            line.split("\t", 1)[1]
                                            if "\t" in line
                                            else ""
                                        )
                                        if saved_annotation == annotation_text:
                                            found_correct_data = True
                                            break

                                if found_correct_data:
                                    # Очищаем кэш load_annotation_data, чтобы при следующей загрузке
                                    # статусы загрузились из правильного места
                                    load_annotation_data.clear()
                                    st.success(
                                        f"Данные для {current_image_name} сохранены в {annotation_file_path}"
                                    )
                                else:
                                    st.warning(
                                        f"Предупреждение: данные для {current_image_name} могут не быть сохранены в файл. "
                                        f"Ожидалось: '{annotation_text}', найдено в файле: {file_content[:200]}"
                                    )
                        except (IOError, OSError) as e:
                            st.error(f"Ошибка при сохранении файла аннотаций: {e}")

                        if (
                            st.session_state.current_image_idx
                            < len(st.session_state.image_files) - 1
                        ):
                            st.session_state.current_image_idx += 1
                        st.rerun()

                    # Обработка сценария "Рукописный текст"
                    if handwritten_button:
                        try:
                            # Относительный путь исходного изображения из файла разметки
                            rel_path = current_relative_path

                            base_dir = st.session_state.image_base_directory

                            # Папка для рукописных изображений внутри рабочей директории
                            handwritten_images_root = os.path.join(
                                base_dir, "handwritten_images"
                            )

                            # Полный путь, куда копируем изображение, сохраняя относительную структуру
                            dest_full_path = os.path.join(
                                handwritten_images_root, rel_path
                            )
                            os.makedirs(os.path.dirname(dest_full_path), exist_ok=True)

                            # Копируем файл
                            shutil.copy2(current_full_image_path, dest_full_path)

                            # Относительный путь, который будем писать в handwritten.txt
                            rel_handwritten_path = os.path.join(
                                "handwritten_images", rel_path
                            ).replace("\\", "/")

                            handwritten_txt_path = os.path.join(
                                base_dir, "handwritten.txt"
                            )
                            # Используем значение из session_state
                            annotation_text_for_handwritten = st.session_state.get(
                                f"annotation_text_{current_image_name}",
                                text_input_value,
                            )
                            new_line = f"{rel_handwritten_path}\t{annotation_text_for_handwritten}\n"

                            # Проверяем, есть ли уже такая строка в handwritten.txt
                            is_duplicate = False
                            if os.path.exists(handwritten_txt_path):
                                with open(
                                    handwritten_txt_path, "r", encoding="utf-8"
                                ) as hw_file:
                                    for line in hw_file:
                                        if line == new_line:
                                            is_duplicate = True
                                            break

                            if is_duplicate:
                                st.info("Эта запись уже присутствует в handwritten.txt")
                            else:
                                with open(
                                    handwritten_txt_path, "a", encoding="utf-8"
                                ) as hw_file:
                                    hw_file.write(new_line)

                                st.success(
                                    "Изображение и разметка добавлены в handwritten.txt как рукописный текст."
                                )
                        except OSError as e:
                            st.error(f"Не удалось сохранить как рукописный текст: {e}")

                # --- Кнопки действий вне формы ---
                col_action1, col_action2 = st.columns([1, 3])
                with col_action1:
                    if st.button(
                        "Удалить изображение",
                        key=f"delete_button_{current_image_name}",
                    ):
                        delete_current_image()
                        st.rerun()  # Перезапускаем приложение после удаления
                with col_action2:
                    pass

                # Кнопки навигации должны быть вне формы
                col_nav1, col_nav2, col_nav3, col_nav4 = st.columns(
                    [1, 1, 1, 1]
                )  # Добавляем колонки для кнопок поворота

                with col_nav1:
                    if st.button(
                        "← Предыдущее",
                        disabled=(st.session_state.current_image_idx == 0),
                        key="prev_button",
                    ):
                        st.session_state.current_image_idx -= 1
                        st.rerun()

                with col_nav2:
                    if st.button(
                        "Следующее →",
                        disabled=(
                            st.session_state.current_image_idx
                            == len(st.session_state.image_files) - 1
                        ),
                        key="next_button",
                    ):
                        st.session_state.current_image_idx += 1
                        st.rerun()
                with col_nav3:
                    if st.button("Повернуть влево", key="rotate_left_button"):
                        rotate_current_image("left")
                with col_nav4:
                    if st.button("Повернуть вправо", key="rotate_right_button"):
                        rotate_current_image("right")

                st.markdown(
                    "--- Отредактируйте текст при необходимости и нажмите 'Подтвердить' для сохранения и перехода к следующему изображению. ---"
                )

            # Обновление current_page, если current_image_idx изменился (например, через навигацию кнопками)
            # Это нужно для синхронизации, если current_image_idx меняется вне пагинации
            expected_page = (
                st.session_state.current_image_idx // st.session_state.page_size
            )
            if st.session_state.current_page != expected_page:
                st.session_state.current_page = expected_page
                st.rerun()

    # Сохраняем все размеченные данные в файл, когда st.session_state.annotations обновляется


if __name__ == "__main__":
    main()
