# Runbook

Локальный спайк без продакшн-деплоя, CI/CD или системы алертинга — этот
runbook покрывает только то, что реально существует: запуск, проверку
состояния и типичные проблемы. Не содержит процедур эскалации/on-call, так
как их в проекте нет.

## Запуск

### Локально (без Docker)
```bash
# Frontend
cd frontend && streamlit run app.py --server.enableXsrfProtection=false

# Backend (из корня репозитория — абсолютные импорты backend.*)
uvicorn backend.main:app --reload
```

### Docker Compose
```bash
docker compose up --build
```
Frontend: http://localhost:8501, backend: http://localhost:8756. Подробности
монтирования `./data` и volume'ов моделей — в `docs/docker.md`.

## Проверка состояния ("health check")

Backend не имеет отдельного `/health`, но `GET /models/status` даёт
эквивалентный сигнал готовности:

```bash
curl http://127.0.0.1:8756/models/status
```
Ответ: `{"paddle": {...}, "surya": {...}, "tesseract": {...}}`, каждое —
`{"status": "not_checked"|"checking"|"ready"|"error", "detail": ...}`.
Frontend опрашивает этот же эндпоинт в `generation_view.py::_render_model_status`.

Job-статус конкретного запуска: `GET /status/{job_id}` →
`{"status": "running"|"done"|"error", "error": ...}`.

## Типичные проблемы

| Симптом | Причина | Что делать |
|---|---|---|
| `models/status.tesseract == "error"` | Системный Tesseract не установлен или отсутствует языковой пакет | Установить `tesseract-ocr`, проверить `tesseract --list-langs` содержит `rus`/`eng` (см. `backend/README.md`) |
| Первый запуск backend'а очень долгий | PaddleOCR/SuryaOCR скачивают модели при первом использовании | Дождаться; при повторных запусках через Docker — убедиться, что volume'ы `paddleocr-models`/`surya-models` не пересозданы |
| Job "застрял" в `running` после перезапуска backend'а | Состояние задач хранится только в памяти процесса (`backend/jobs.py`) | Ожидаемое поведение для спайка — перезапустить job через `POST /run` |
| Горячие клавиши ←/→ не работают | JS-обработчик матчится по буквальному тексту кнопок, легко ломается косметическими изменениями | См. хрупкое место в `docs/architecture.md`; проверить, не изменился ли текст кнопок в `editor_view.py` |
| Повёрнутое изображение показывает старую превьюшку | Кэш `st.cache_data` не сброшен корректно | См. хрупкое место в `docs/architecture.md` (связка `image_ops.py`) |
| `POST /run` принимает произвольный путь и перезаписывает файлы там | Осознанное отсутствие валидации путей — локальный однопользовательский спайк без аутентификации | Не запускать backend на общей/многопользовательской машине как есть (см. `backend/README.md`) |

## Откат

Нет CI/CD и нет тегированных релизов — откат = `git revert`/`git checkout`
нужного коммита в `main`. Для Docker-образов — пересборка (`docker compose up
--build`) после отката кода; именованные volume'ы с моделями откатывать не
нужно (формат кэша моделей не версионируется в этом репозитории).

## Мониторинг и алертинг

Не настроены. Единственный сигнал — ручной опрос `/models/status` и
`/status/{job_id}` (см. выше) либо логи процесса (`uvicorn`/`streamlit` stdout).
