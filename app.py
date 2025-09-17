import streamlit as st
import os
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


@st.cache_data
def load_annotation_data(
    file_contents: str, image_base_directory: str, working_dir_for_cache: str
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

        # Загрузка кэша статусов
        status_cache_file_path = os.path.join(working_dir_for_cache, "status_cache.txt")
        if os.path.exists(status_cache_file_path):
            with open(status_cache_file_path, "r", encoding="utf-8") as f:
                cached_marked_images = set(f.read().splitlines())

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
        status_cache_file_path = os.path.join(
            st.session_state.working_dir, "status_cache.txt"
        )
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
    annotation_file_path = st.session_state.annotation_file_path
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
    st.info(f"Файл аннотаций обновлен после удаления {current_image_name}.")

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

    if uploaded_annotation_file is not None:
        # Временное сохранение загруженного файла для дальнейшей обработки
        file_contents = uploaded_annotation_file.read().decode("utf-8")
        temp_file_path = os.path.join(
            "temp_data", uploaded_annotation_file.name
        )  # Создаем временную папку
        os.makedirs(os.path.dirname(temp_file_path), exist_ok=True)
        with open(temp_file_path, "w", encoding="utf-8") as f:
            f.write(file_contents)

        st.session_state.annotation_file_path = temp_file_path

        if not os.path.exists(st.session_state.annotation_file_path):
            st.error("Загруженный файл не найден.")
            return
        if not os.path.isfile(st.session_state.annotation_file_path):
            st.error("Загруженный файл не является файлом.")
            return

        # Рабочая директория для кэша статусов (там, где временно сохранен файл разметки)
        working_dir_for_cache = os.path.dirname(st.session_state.annotation_file_path)
        st.session_state.working_dir = working_dir_for_cache

        # Добавляем поле для ввода базовой директории изображений
        if "image_base_directory" not in st.session_state:
            st.session_state.image_base_directory = ""
        image_base_directory = st.text_input(
            "Укажите рабочую директорию",
            value=st.session_state.image_base_directory,
        )

        if not image_base_directory:
            st.warning("Пожалуйста, укажите рабочую директорию.")
            return
        if not os.path.isdir(image_base_directory):
            st.error("Указанная рабочая директория не существует.")
            return
        # Вызываем кэшированную функцию для загрузки всех данных
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
            working_dir_for_cache,
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
            # Если текущая страница или индекс изображения выходят за пределы нового отфильтрованного списка
            if st.session_state.current_page >= total_pages:
                st.session_state.current_page = (
                    total_pages - 1 if total_pages > 0 else 0
                )

            # Убедимся, что current_image_idx указывает на действительное изображение в ОТФИЛЬТРОВАННОМ списке
            # и что оно находится на текущей странице.
            # Сначала найдем текущий original_index_in_full_list в display_image_files.
            try:
                current_global_idx_in_filtered = display_image_files.index(
                    st.session_state.image_files[st.session_state.current_image_idx]
                )
                # Если текущий global_idx_in_filtered не на текущей странице, перейдем на страницу этого изображения
                expected_page_for_current_image = (
                    current_global_idx_in_filtered // st.session_state.page_size
                )
                if st.session_state.current_page != expected_page_for_current_image:
                    st.session_state.current_page = expected_page_for_current_image
            except (
                ValueError
            ):  # текущее изображение не найдено в отфильтрованном списке
                st.session_state.current_image_idx = st.session_state.image_files.index(
                    display_image_files[0]
                )  # Переходим к первому изображению в отфильтрованном списке
                st.session_state.current_page = 0
                st.rerun()  # Нужно перезапустить, чтобы обновить UI

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
                current_image_name = os.path.basename(current_full_image_path)
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
                # print(f"Время отображения текущего изображения: {time.time() - st3}") # Удаляем таймер

                default_text = st.session_state.annotations.get(current_image_name, "")

                with st.form(key=f"annotation_form_{current_image_name}"):
                    st.session_state.current_text_annotation = st.text_input(
                        "Текст с изображения",
                        value=default_text,
                        key=f"text_input_form_{current_image_name}",
                    )
                    # Обработка переносов строки - замена на пробелы
                    st.session_state.current_text_annotation = (
                        st.session_state.current_text_annotation.replace(
                            "\n", " "
                        ).replace("\r", " ")
                    )

                    col_form1, col_form2 = st.columns([1, 2])
                    with col_form1:
                        submit_button = st.form_submit_button("Подтвердить")
                    with col_form2:
                        pass

                    if submit_button:
                        st.session_state.annotations[current_image_name] = (
                            st.session_state.current_text_annotation
                        )
                        st.session_state.status_icons[current_image_name] = (
                            "✅"  # Отмечаем как размеченное зеленой галочкой
                        )

                        # Обновляем кэш отмеченных изображений (храним basename)
                        st.session_state.cached_marked_images.add(current_image_name)
                        status_cache_file_path = os.path.join(
                            st.session_state.working_dir, "status_cache.txt"
                        )
                        with open(status_cache_file_path, "w", encoding="utf-8") as f:
                            for img_name in st.session_state.cached_marked_images:
                                f.write(f"{img_name}\n")
                        st.info(
                            f"Статус для {current_image_name} сохранен в {status_cache_file_path}"
                        )

                        # Сохраняем данные разметки в файл аннотаций после каждого подтверждения (храним относительный путь)
                        annotation_file_path = st.session_state.annotation_file_path
                        with open(annotation_file_path, "w", encoding="utf-8") as f:
                            for relative_path_for_saving in st.session_state.original_relative_paths_for_saving:  # Итерируемся по оригинальному списку относительных путей
                                img_name_for_saving = os.path.basename(
                                    os.path.normpath(
                                        os.path.join(
                                            st.session_state.image_base_directory,
                                            relative_path_for_saving,
                                        )
                                    )
                                )
                                annotation_text_to_save = (
                                    st.session_state.annotations.get(
                                        img_name_for_saving, ""
                                    )
                                )
                                f.write(
                                    f"{relative_path_for_saving}\t{annotation_text_to_save}\n"
                                )

                        load_annotation_data.clear()  # Очищаем кэш, чтобы данные перезагрузились

                        st.success(
                            f"Данные для {current_image_name} сохранены в {annotation_file_path}"
                        )

                        if (
                            st.session_state.current_image_idx
                            < len(st.session_state.image_files) - 1
                        ):
                            st.session_state.current_image_idx += 1
                        st.rerun()

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
