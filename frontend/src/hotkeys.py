# JS matches nav buttons by literal '←'/'→' text in editor_view.py —
# keep button labels unchanged or hotkeys silently break.
from streamlit.components.v1 import html


def register_hotkeys():
    """Регистрирует горячие клавиши через HTML/JS компонент"""
    hotkeys_html = """
    <script>
    // Удаляем предыдущий обработчик если есть
    if (window.hotkeyHandler) {
        document.removeEventListener('keydown', window.hotkeyHandler);
        window.parent.document.removeEventListener('keydown', window.hotkeyHandler);
    }

    window.hotkeyHandler = function(e) {
        const parent = window.parent;

        // Игнорируем если фокус в input/textarea
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            return;
        }

        // Стрелка влево
        if (e.key === 'ArrowLeft') {
            e.preventDefault();
            // Ищем кнопку навигации с символом ←
            const buttons = parent.document.querySelectorAll('button');
            buttons.forEach(btn => {
                if (btn.textContent.includes('←') && !btn.disabled) {
                    btn.click();
                }
            });
        }
        // Стрелка вправо
        else if (e.key === 'ArrowRight') {
            e.preventDefault();
            // Ищем кнопку навигации с символом →
            const buttons = parent.document.querySelectorAll('button');
            buttons.forEach(btn => {
                if (btn.textContent.includes('→') && !btn.disabled) {
                    btn.click();
                }
            });
        }
    };

    document.addEventListener('keydown', window.hotkeyHandler);
    parent.document.addEventListener('keydown', window.hotkeyHandler);

    console.log('Hotkeys registered: ← → arrows for image navigation');
    </script>
    """
    html(hotkeys_html, height=0)
