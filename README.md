# docs-places-parser

Парсер достопримечательностей из DOCX (структура «район / файлы»), обогащение через OpenRouter, поиск изображений.

## Требования

- Python **3.11+**
- [Poetry](https://python-poetry.org/docs/#installation)

## Установка

```bash
poetry install
```

Активировать окружение Poetry или запускать команды через `poetry run`.

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `OPENROUTER_API_KEY` | Ключ API [OpenRouter](https://openrouter.ai/) |

Шаблон без секретов: [.env.example](.env.example). Скопируйте в `.env` или экспортируйте переменную в shell.

## Запуск

Минимальный пример (ключ в окружении):

```bash
export OPENROUTER_API_KEY="ваш-ключ"
poetry run python main.py \
  --input objects_list \
  --districts tatarstan_locations.json \
  --api-key "$OPENROUTER_API_KEY"
```

Готовый сценарий (два прогона с разными входными папками):

```bash
export OPENROUTER_API_KEY="ваш-ключ"
./run.sh
```

### Каталог вывода

По умолчанию артефакты пишутся в **`output/`**:

- `output/attractions.json` — итоговый JSON (`--output` / `-o`, путь относительно `--output-dir`, если не абсолютный);
- `output/attractions_quality_report.json` — отчёт по качеству;
- `output/processing_cache.json`, `processing_state.json`, `processing_errors.json` — кэш, возобновление и ошибки;
- `output/progress_backup.json` — периодический бэкап прогресса.

Сменить каталог:

```bash
poetry run python main.py --input objects_list --api-key "$OPENROUTER_API_KEY" --output-dir ./build/out
```

Продолжить после обрыва: добавьте флаг `--resume` (читается `processing_state.json` в выбранном `--output-dir`).

## Полезные флаги

См. справку:

```bash
poetry run python main.py --help
```

Кратко: `--model`, `--districts`, `--skip-photos`, `--max-files`, `--only-district`, `--resume`, `--min-description-paragraphs`, `--retry-count`.
