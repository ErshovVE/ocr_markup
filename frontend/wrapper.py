import os
import sys

from streamlit.web import cli as stcli


def resource_path(relative_path):
    """ Получить путь к ресурсу при сборке в .exe """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


if __name__ == "__main__":
    app_path = resource_path("app.py")
    sys.argv = [
        "streamlit",
        "run",
        app_path,
        "--global.developmentMode=false",
        "--server.headless=true"
    ]

    # Запуск Streamlit
    sys.exit(stcli.main())
