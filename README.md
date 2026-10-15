# SERAPHIM

Локально управляемая, модульная AI-среда.

## Стек (принятый в S02)

| Компонент | Технология | Обоснование |
|---|---|---|
| Backend | Python (stdlib + dev tooling) | ADR-001, прототип 24/24 PASS |
| Desktop (VESSEL) | Electron | ADR-002, Tauri failed (rc.exe) |
| GUI ↔ CORE API | HTTP/loopback + token | ADR-003 |

## Обязательные версии runtime

| Инструмент | Минимальная версия |
|---|---|
| Python | 3.11+ (требование pyproject.toml) |
| pip / Python package manager | штатный из Python 3.11+ |
| Node.js | 20+ (экспериментальная среда: 24.18.0) |
| npm | 10+ (штатный из Node 20+) |
| Electron | ^44.7.2 (stable от 13.10.2026) |

> **Важно:** Python 3.11+ требуется для избежания EOL Python 3.10 (1 октября 2026). Production-версии выбираются из поддерживаемых stable-веток при финальной сборке (S77).

## Быстрый старт

### 1. Подготовка среды

```powershell
# Убедитесь, что структура каталогов существует
# (shared/testroot должен существовать для прохождения тестов)
# Обычно каталог отслеживается через .gitkeep, но для первого клонирования:
if (-not (Test-Path "shared\testroot")) {
    New-Item -ItemType Directory -Force -Path "shared\testroot" | Out-Null
}
```

Для Unix/Linux/macOS:

```bash
# Убедитесь, что testroot существует
mkdir -p shared/testroot
```

### 2. Clean install

```powershell
# Создайте Python venv в корне проекта (игнорируется git)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Electron VESSEL
npm install
```

### 3. Build (скелет — проверка импорта)

```powershell
# Python: линтер
ruff check backend/

# Electron: проверка package.json валиден
npm run build
```

### 4. Test

```powershell
# Python: запуск pytest (из корня)
pytest

# Electron: placeholder
npm run test
```

### 5. Lint + Format

```powershell
# Ruff (Python)
ruff check backend/        # lint
ruff format backend/       # форматирование
ruff check --fix backend/  # автофикс

# JS/TS: не настроен на S03
```

### 6. Type-check (placeholder)

```powershell
# На S03 типизация Python не настроена (mypy отложен до S06+)
# Команда-заглушка:
echo "Type-check not configured for S03 skeleton. Use 'ruff check' for lint."
```

## Структура проекта

```
.
├── backend/                  # Python backend (CORE, SANCTUM, WINGS...)
│   ├── seraphim/             # Пакет seraphim (core, sanctum, wings...)
│   ├── tests/                # Python-тесты
│   ├── scripts/              # CLI-скрипты (seraphim, doctor...)
│   └── pyproject.toml        # Зависимости, ruff, pytest
├── ui-electron/              # Electron VESSEL (main, preload, index)
├── shared/                   # Общие ресурсы
│   └── testroot/             # Тестовый root (не user data)
├── scripts/                  # Проектные скрипты (CI, setup)
├── docs/                     # Документация (ADR, спецификации)
├── prototypes/               # Изолированные прототипы (S02 proof)
├── pyproject.toml            # Корневой pyproject (backend metadata)
├── package.json              # Корневой package.json (Electron)
├── .gitignore
├── IMPLEMENTATION_PLAN.md
├── IMPLEMENTATION_LOG.md
├── ARCHITECTURE_DECISIONS.md
└── CONTRACTS.md
```

## Что НЕ попадает в git

- `node_modules/`, `.venv/`, `venv/` — виртуальные окружения
- `*.pyc`, `__pycache__/` — байт-код Python
- `data/*.sqlite*` — файлы базы данных
- `logs/`, `artifacts/` — журналы и артефакты
- `*.log`, `*.key`, `*.pem` — логи и секреты
- `.vscode/`, `.idea/` — настройки IDE
- `dist/`, `build/` — артефакты сборки
- `prototypes/**/*.exe`, `*.dll`, `*.so` — бинарники прототипов
- Секреты (API keys, токены)

## Критерии приёмки S03

- [x] Чистая сборка и запуск работают по документации
- [x] Быстрые проверки: `ruff check backend/` и `pytest`
- [x] Нет секретов, node_modules, .venv, бинарников в git
- [ ] Проверить вручную: повторить clean build по этому README

## Этапы

Полный план: `IMPLEMENTATION_PLAN.md` (этапы S00–S77).
Журнал: `IMPLEMENTATION_LOG.md`.
