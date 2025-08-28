import streamlit as st
import os
import glob
from PIL import Image

st.set_page_config(layout="wide")


def main():
    st.title("Инструмент разметки OCR")

    if "working_dir" not in st.session_state:
        st.session_state.working_dir = ""

    working_dir = st.text_input(
        "Укажите рабочую папку", value=st.session_state.working_dir
    )
    if working_dir:
        st.session_state.working_dir = working_dir
        if not os.path.isdir(working_dir):
            st.error("Указанная папка не существует.")
            return
        st.success(f"Рабочая папка: {working_dir}")

        # Изменяем rec_file_path на gt_file_path и всегда используем rec_gt.txt
        gt_file_path = os.path.join(working_dir, "rec_gt.txt")
        if os.path.exists(gt_file_path):
            with open(gt_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            st.session_state.annotations = {
                line.split("\t")[0]: line.split("\t")[1].strip()
                for line in lines
                if "\t" in line
            }
            st.info(f"Загружен файл разметки: {gt_file_path}")
            # Отмечаем все загруженные изображения как размеченные
            # st.session_state.marked_images = set(st.session_state.annotations.keys())
        else:
            st.session_state.annotations = {}
            st.warning(
                f"Файл разметки {gt_file_path} не найден. Создан пустой файл разметки."
            )

        image_files = []
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tiff"):
            image_files.extend(glob.glob(os.path.join(working_dir, ext)))
        image_files = sorted(
            [os.path.basename(f) for f in image_files]
        )  # Store only base names

        if not image_files:
            st.warning("В выбранной папке не найдено изображений.")
            return

        st.session_state.image_files = image_files
        if "current_image_idx" not in st.session_state:
            st.session_state.current_image_idx = 0

        # Инициализация/обновление status_icons
        if (
            "status_icons" not in st.session_state
            or st.session_state.get("last_working_dir") != working_dir
            or st.session_state.get("last_image_files") != image_files
        ):
            st.session_state.status_icons = {}
            for img_name in image_files:
                if img_name not in st.session_state.annotations:
                    st.session_state.status_icons[img_name] = (
                        "❌"  # Красный крестик, если нет разметки
                    )
                else:
                    st.session_state.status_icons[img_name] = (
                        "❓"  # Серый знак вопроса, если есть разметка, но не подтверждена в текущей сессии
                    )
            st.session_state.last_working_dir = working_dir
            st.session_state.last_image_files = image_files

    else:
        return

    # Отображение основной части приложения только если рабочая папка выбрана и есть изображения
    if "image_files" in st.session_state and st.session_state.image_files:
        col1, col2 = st.columns([1, 2])

        with col1:
            st.subheader("Список изображений")
            # Используем st.container с фиксированной высотой для прокрутки списка изображений
            with st.container(height=600):
                for i, img_name in enumerate(st.session_state.image_files):
                    display_name = img_name
                    icon = st.session_state.status_icons.get(
                        img_name, ""
                    )  # Получаем иконку статуса
                    display_name = f"{display_name} {icon}"
                    if st.button(display_name, key=f"img_select_{i}"):
                        st.session_state.current_image_idx = i

        with col2:
            current_image_name = st.session_state.image_files[
                st.session_state.current_image_idx
            ]
            current_image_path = os.path.join(
                st.session_state.working_dir, current_image_name
            )
            st.subheader(f"Текущее изображение: {current_image_name}")

            try:
                image = Image.open(current_image_path)
                # Изменение размера изображения до 48 пикселей по вертикали
                original_width, original_height = image.size
                new_height = 48
                new_width = int(original_width * (new_height / original_height))
                image = image.resize((new_width, new_height), Image.LANCZOS)

                # Явно указываем ширину и высоту для st.image и убираем подпись
                st.image(image, width=new_width, use_column_width=False)
            except Exception as e:
                st.error(f"Ошибка при загрузке изображения {current_image_name}: {e}")

            default_text = st.session_state.annotations.get(current_image_name, "")

            with st.form(key=f"annotation_form_{current_image_name}"):
                st.session_state.current_text_annotation = st.text_input(
                    "Текст с изображения",
                    value=default_text,
                    key=f"text_input_form_{current_image_name}",
                )
                # Обработка переносов строки - замена на пробелы
                st.session_state.current_text_annotation = (
                    st.session_state.current_text_annotation.replace("\n", " ").replace(
                        "\r", " "
                    )
                )

                col_form1, col_form2 = st.columns([1, 2])
                with col_form1:
                    submit_button = st.form_submit_button("Подтвердить")
                with col_form2:
                    # Удаляем кнопку "Сохранить все размеченные данные", так как сохранение происходит автоматически
                    pass

                if submit_button:
                    st.session_state.annotations[current_image_name] = (
                        st.session_state.current_text_annotation
                    )
                    st.session_state.status_icons[current_image_name] = (
                        "✅"  # Отмечаем как размеченное зеленой галочкой
                    )

                    # Сохраняем данные в rec_gt.txt после каждого подтверждения
                    gt_file_path = os.path.join(
                        st.session_state.working_dir, "rec_gt.txt"
                    )
                    with open(gt_file_path, "w", encoding="utf-8") as f:
                        for (
                            img_name_key,
                            annotation_text,
                        ) in st.session_state.annotations.items():
                            f.write(f"{img_name_key}\t{annotation_text}\n")
                    st.success(
                        f"Данные для {current_image_name} сохранены в {gt_file_path}"
                    )

                    if (
                        st.session_state.current_image_idx
                        < len(st.session_state.image_files) - 1
                    ):
                        st.session_state.current_image_idx += 1
                    st.experimental_rerun()

            # Кнопки навигации должны быть вне формы
            col_nav1, col_nav2 = st.columns([1, 1])

            with col_nav1:
                if st.button(
                    "← Предыдущее",
                    disabled=(st.session_state.current_image_idx == 0),
                    key="prev_button",
                ):
                    st.session_state.current_image_idx -= 1
                    st.experimental_rerun()

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
                    st.experimental_rerun()

            st.markdown(
                "--- Отредактируйте текст при необходимости и нажмите 'Подтвердить' для сохранения и перехода к следующему изображению. ---"
            )


if __name__ == "__main__":
    main()
