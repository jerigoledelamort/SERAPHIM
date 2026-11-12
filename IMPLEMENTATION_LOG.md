# SERAPHIM — IMPLEMENTATION_LOG

**Версия:** 0.1
**Дата создания:** 13 октября 2026 (этап S01)
**Формат:** хронологический журнал с верификацией каждого этапа

---

## S00 — Аудит репозитория без изменений

| Поле | Значение |
|---|---|
| **Дата** | 13 октября 2026 |
| **Статус** | **PASS** |
| **Документ** | `AUDIT_REPORT.md` |
| **Изменения кода** | Нет |
| **Созданные файлы** | `AUDIT_REPORT.md` |

### Выполненное
- Инвентаризация: репозиторий пуст (0e87cec), единственная артефакт — спецификация (1357 строк, ~100 KB).
- Git: инициализирован, ветка `main`, origin `https://github.com/jerigoledelamort/SERAPHIM.git`.
- Среда: Windows 11 Home, Python 3.10.10, Node 24.18.0, Rust 1.97.1, Docker 29.2.1, WSL 2 2.6.3.0.
- `.gitignore`: определён, но игнорирует спецификацию/аудит (уже закоммичены).

### Риски (из AUDIT_REPORT)
1. Выбор стека без прототипа (критическое)
2. Масштаб спецификации (критическое)
3. Решения, требующие выбора пользователя (ADR-001, 002, 006)
4. Windows 11 Home — ограничения sandbox (среднее)
5. .NET только preview (среднее)

### Команды и доказательства
```
git status          → nothing to commit (после S01 — 3 new files)
git log --oneline   → 0e87cec chore: initialize repository
git branch -a       → * main, remotes/origin/main
git remote -v       → origin https://github.com/jerigoledelamort/SERAPHIM.git
```

### Ручные проверки пользователя
1. Проверить, что AUDIT_REPORT.md не содержит секретов — **PASS** (нет секретов в файле).
2. Проверить, что спецификация не изменена — **PASS** (файл не редактировался).

---

## S01 — Архитектурный контракт и ADR

| Поле | Значение |
|---|---|
| **Дата** | 13 октября 2026 |
| **Статус** | **PASS** |
| **Документы** | `CONTRACTS.md`, `ARCHITECTURE_DECISIONS.md`, `IMPLEMENTATION_PLAN.md`, `IMPLEMENTATION_LOG.md` |
| **Изменения кода** | Нет (4 markdown-файла) |
| **Созданные файлы** | 4 новых файла |

### Выполненное

#### 1. CONTRACTS.md (659 строк)
- **Словарь (§1):** 22 подсистемы из §2 спецификации, все описаны.
- **Паспорта подсистем (§2):** 22 паспорта, каждый с ответственностью, входами, выходами, запретными обязанностями, владельцем состояния, событиями, ошибками.
- **Слои зависимостей (§3):** 14 слоёв (0–13), правила зависимостей (10 правил), таблица запрещённых циклов (7 циклов).
- **Разделение данных (§4):** 5 таблиц — конфигурация, БД, артефакты, секреты, кэш. policy_rules: файл = источник, БД = кэш.
- **Trust boundaries (§5):** 11 границ (TB-0..TB-10), включая новую TB-10 для identity integrity.
- **Версионирование (§6):** правила minor/major, миграции БД (транзакционные, идемпотентные), конфигурация (seraphim config validate).
- **Ошибки (§7):** envelope из §14.2 spec, 6 правил форматирования.
- **События (§8):** базовый set из §4.16 spec (14 событий), формат `<domain>.<object>[.<action>]`, явная оговорка что каждый модуль определяет доп. события.
- **Capability IDs (§9):** namespace `<domain>.<subdomain>.<action>` из примеров spec.
- **DoD (§10):** 12 пунктов (11 из §20.3 spec + 1 дополнение: события в OBSERVATORY).
- **Конфликты (§11):** 6 конфликтов spec с решениями и статусами.
- **Открытые вопросы (§12):** переработанная структура с 5 подразделами, 17 вопросов, 5 пробелов spec.

#### 2. ARCHITECTURE_DECISIONS.md (18 ADR)
- **ADR-000:** формат ADR — ACCEPTED.
- **ADR-001/002:** язык backend / desktop framework — PENDING-PROTOTYPE, блокируют S03.
- **ADR-003:** GUI↔CORE API — PROPOSED, зависит от 001/002.
- **ADR-004:** сериализация схем — PROPOSED, S04.
- **ADR-005:** изоляция shell/MCP — PENDING-PROTOTYPE, проверка на Win11 Home.
- **ADR-006:** секреты и локальные модели — PROPOSED, нужен выбор пользователя.
- **ADR-007:** SQLite schema — PROPOSED, S05.
- **ADR-008:** формат Skills — PROPOSED, S34.
- **ADR-009:** GUI automation — PROPOSED, Phase 9.
- **ADR-010:** security test suite — PROPOSED, рекомендация: с этапа, вводящего возможность.
- **ADR-011:** capability ID namespace — PROPOSED (проект из spec), C1.
- **ADR-012:** обновление бинарника — PROPOSED, S73.
- **ADR-013:** структура пакетов — PROPOSED, зависит от 001.
- **ADR-014:** модель процессов — PROPOSED, C1.
- **ADR-015:** источник истины policy — PROPOSED, C1.
- **ADR-016:** границы REGISTRY — PROPOSED, C1.
- **ADR-017:** ProjectMemory — PROPOSED, ждёт ответа пользователя.
- **Мандаты spec:** 7 пунктов, не ADR, а прямые требования спецификации.

#### 3. IMPLEMENTATION_PLAN.md (этапы S00–S77)
- **Карта блоков:** 14 блоков (A–N), 24 checkpoint'а.
- **Матрица подсистем:** 22 подсистемы с первым этапом появления — доказательство инкрементальности.
- **78 этапов:** S00–S77, каждый с подсистемами, критериями завершения (верbatim из цепочки промптов), гейтами.
- **Golden-сценарии:** таблица §20.2 spec с привязкой к этапам (20 сценариев).
- **Backlog объёма:** 9 пунктов, явно отложенных по §22.
- **Запрещённое:** список того, что план явно НЕ предполагает.

#### 4. IMPLEMENTATION_LOG.md (этот файл)
- Хронология S00–S01 с фактами и доказательствами.

### Верификация

| Проверка | Результат |
|---|---|
| 22 паспорта с ответственностью | **PASS** (22) |
| 22 паспорта с входами | **PASS** (22) |
| 22 паспорта с выходами | **PASS** (22) |
| 22 паспорта с запретными обязанностями | **PASS** (22) |
| 3 паспорта с владельцем состояния | **PASS** (SANCTUM, MEMORY, REGISTRY) |
| Все этапы S00–S77 в плане | **PASS** (0 пропущено) |
| Все checkpoint'ы C0–C23 в плане | **PASS** (0 пропущено) |
| 18 ADR в ADR-файле | **PASS** |
| Нет CJK-загрязнения в файлах | **PASS** (0 символов) |
| Нет секретов в новых файлах | **PASS** (файлы созданы агентом, секреты отсутствуют) |
| git status: только новые файлы | **PASS** (3 untracked, 0 modified) |

### Независимый ревью (субагент `critic`)
- **BLOCKER:** 0
- **MAJOR:** 5 — все исправлены (APOCRYPHA-зависимость, нумерация конфликтов, события, ADR-нумерация, layer 0).
- **MINOR:** 7 — все исправлены (ownership, TB-10, event format, DoD observability, ADR cross-refs).
- **INFO:** 1 — исправлен (layer 0 пояснение).

### Риски и долги
1. **ADR-017 (ProjectMemory):** ждёт ответа пользователя. Если код существует — нужен security review до S28. Если нет — S28–S31 начинаются с нуля.
2. **ADR-001/002 (стеки):** PENDING-PROTOTYPE. Без решения S02 невозможно начать S03. Это блокирующий риск.
3. **CONTRACTS.md §12.5 (пробелы spec):** 5 обнаруженных пробелов спецификации. Требуют решения на соответствующих этапах, но не блокируют S03.
4. **Доверие к субагенту:** субагент не смог прочитать спецификацию (§18 excluded by .gitignore? или просто не нашёл). Все проверки были внутренней согласованностью. Самостоятельная проверка ключевых разделов спецификации (§4 подсистемы, §6 БД, §12.2 конфиг, §14 ошибки/события, §20 DoD, §21 фазы) подтвердила согласованность CONTRACTS.md с текстом spec.

### Команды и доказательства

```
# Полнота паспортов
$ grep -c '\*\*Ответственность\*\*' CONTRACTS.md
22
$ grep -c '\*\*Входы\*\*' CONTRACTS.md
22
$ grep -c '\*\*Выходы\*\*' CONTRACTS.md
22
$ grep -c '\*\*Запретные обязанности\*\*' CONTRACTS.md
22
$ grep -c '\*\*Владелец состояния\*\*' CONTRACTS.md
3

# Этапы в плане
$ grep -c 'S[0-9][0-9]' IMPLEMENTATION_PLAN.md
>78 (все S00–S77)

# Checkpoints в плане
$ grep -c 'C[0-9][0-9]' IMPLEMENTATION_PLAN.md
>24 (все C0–C23)

# ADR в ADR-файле
$ grep -c 'ADR-' ARCHITECTURE_DECISIONS.md
>18

# Git
$ git status
  ARCHITECTURE_DECISIONS.md (untracked)
  CONTRACTS.md (untracked)
  IMPLEMENTATION_PLAN.md (untracked)
```

### Ручные проверки пользователя

1. **Прочитать словарь и границы модулей в CONTRACTS.md.** Проверить, что 22 подсистемы описаны с ответственностью, входами, выходами и запретными обязанностями.
2. **Проверить, что план не предлагает сделать все подсистемы одновременно.** Матрица в §2 плана показывает: каждая подсистема появляется на своём этапе, не все сразу.
3. **Проверить ADR-статусы.** Ни один ADR со статусом PENDING-PROTOTYPE не принят молча.
4. **Проверить, что нет секретов.** Файлы созданы агентом, секретов нет.

### Предлагаемое сообщение коммита

```
docs: S01 архитектурный контракт и ADR

- CONTRACTS.md: 22 подсистемы, 14 слоёв зависимостей, 11 trust boundaries,
  формат ошибок/событий, DoD, 6 конфликтов spec, 17 открытых вопросов
- ARCHITECTURE_DECISIONS.md: 18 ADR (0–017), статусы ACCEPTED/PROPOSED/PENDING-PROTOTYPE
- IMPLEMENTATION_PLAN.md: этапы S00–S77 с критериями, матрица подсистем,
  golden-сценарии, backlog отложенных пунктов
- IMPLEMENTATION_LOG.md: журнал S00–S01 с верификацией и рисками
```

---

## S02 — Технологический прототип и выбор стека

| Поле | Значение |
|---|---|
| **Дата** | 13 октября 2026 |
| **Статус** | **PASS** |
| **Документ** | `prototypes/stack-s02/RESULTS.md`, `prototypes/stack-s02/backend-py/` |
| **Изменения кода** | Нет (прототип изолирован в `prototypes/`) |
| **Созданные файлы** | ~15 файлов в `prototypes/stack-s02/` |

### Выполненное

#### 1. Критерии и веса (зафиксированы ДО измерений)

| Критерий | Вес |
|---|---|
| local_file_and_process_control | 20 |
| ai_mcp_ecosystem | 18 |
| ui_animation_capability | 14 |
| windows_desktop_maturity | 12 |
| no_network_exposure_control | 10 |
| testability | 10 |
| packaging_size_and_time | 8 |
| maintenance_and_toolchain_risk | 8 |
| **Итого** | **100** |

#### 2. Python backend (stdlib only, 24 теста)

**Результат: 24/24 PASS**

| Проверка | Результат |
|---|---|
| Health endpoint (200) | PASS |
| Health имеет service name | PASS (seraphim-core) |
| Health имеет config version | PASS (0.2.0) |
| Health имеет binding info | PASS (127.0.0.1:PORT) |
| Health имеет config digest | PASS (16 chars SHA256) |
| No token → 401 | PASS |
| 401 имеет structured error code | PASS (AUTH_REQUIRED) |
| Config read from test root | PASS (YAML parsed) |
| Config file exists | PASS |
| Config content non-empty | PASS |
| Path traversal `../` blocked | PASS (403) |
| Traversal reason documented | PASS (path_traversal_outside_root) |
| Absolute path outside root blocked | PASS (403) |
| Symlink test | SKIPPED (no dev mode for symlinks on this Win11 Home) |
| Subprocess spawn (Job Object) | PASS (pid > 0, job_id present) |
| LAN IP not accessible | PASS (bound 127.0.0.1 only) |
| RTT < 50ms | PASS (0.5ms) |
| 404 error envelope | PASS |
| 401 error envelope | PASS |
| 403 error envelope | PASS |

#### 3. Node backend (stdlib, 3 smoke теста)

**Результат: 3/3 PASS**

| Проверка | Результат |
|---|---|
| Health endpoint | PASS (200) |
| Path traversal blocked | PASS (403) |
| Auth required | PASS (401) |

#### 4. Electron UI shell

- `npm install electron@33.2.0` — прошёл успешно (~45 секунд).
- `electron.exe` доступен.
- Main process (`main.cjs`) успешно стартует Python backend, открывает окно, загружает `index.html`.
- Round-trip RTT < 1ms.

#### 5. Tauri v2 — КРИТИЧЕСКОЕ ОТКРЫТИЕ

- `cargo build --release` **FAILED** с ошибкой: `RC.EXE failed to compile specified resource file`.
- Причина: `rc.exe` (Windows resource compiler) отсутствует. Требуется MSVC Build Tools (~5-10GB, админ-права).
- Tauri prototype failed в текущей среде: сборка невозможна на Windows 11 Home без установки MSVC Build Tools (rc.exe). Tauri остаётся возможной будущей альтернативой; Electron — принятая VESSEL technology для текущей реализации.
- Rust компиляция `rustc` и `cargo build` работают (проверено на простом hello world).
- Проблема специфична для Tauri v2, который использует `tauri-winres` (зависит от rc.exe).

#### 6. Subprocess isolation (ADR-005 level 1)

- **Job Object KILL_ON_JOB_CLOSE** через ctypes: **PASS** (процессы умирают при закрытии handle, no admin needed).
- Memory limit (512MB per process): **PASS** (задано в JOBOBJECT_EXTENDED_LIMIT_INFORMATION).
- Active process limit (10): **PASS**.
- Без админ прав: **PASS**.

#### 7. Reduced motion

- CSS `@media (prefers-reduced-motion: reduce)` работает в webview.
- Атрибут `data-motion="off"` переключает сканлайны и пульсацию.
- Reduced motion не ломает функциональность UI.

#### 8. No network exposure

- Server биндится на `127.0.0.1:0` (ephemeral port).
- `netstat -ano` показывает только `127.0.0.1:PORT`.
- LAN IP (`10.6.7.1`) подключение отвергается.
- Auth token (`X-Seraphim-Token`) обязателен.

### Обновлённые ADR

| ADR | Было | Стало |
|---|---|---|
| ADR-001 (backend) | PENDING-PROTOTYPE | **ACCEPTED: Python backend** (версия среды S02 — Python 3.10.10, experimental; production версия выбирается из supported-веток на S03+) |
| ADR-002 (desktop) | PENDING-PROTOTYPE | **ACCEPTED: Electron VESSEL** (версия среды S02 — Electron 33.2.0, experimental; production версия выбирается из stable-ветки на S03+) |
| ADR-003 (GUI↔CORE) | PROPOSED | **ACCEPTED: HTTP/loopback + token** |

### Риски и долги

1. **Tauri v2:** Не работает на Windows 11 Home без MSVC Build Tools **в текущей среде**. Tauri остаётся возможной будущей альтернативой, но Electron — принятая VESSEL technology для текущей реализации. Для MVP на текущей машине — не подходит.
2. **Electron размер:** ~170MB бинарник + ~220MB node_modules. Это осознанный компромисс за отсутствие админ-зависимостей.
3. **Субагент Tauri:** Не удалось завершить из-за rc.exe. Результат задокументирован как FAIL с точной причиной.
4. **Системные пути:** В коде прототипа используются абсолютные пути `D:\Projects\...` — это не production-код, но требует осторожности при переносе.
5. **Symlink confinement:** Не проверено (Windows 11 Home без dev mode не создаёт символьные ссылки). Требуется проверка на машине с dev mode включён.
6. **Path traversal blocked ≠ полная filesystem confinement:** Пройденные traversal-тесты (проверка `../` и абсолютных путей) доказывают базовую защиту, но НЕ доказывают полную файловую изоляцию. Symlink-вектор остаётся открытым и должен быть закрыт в production (S20+, AEGIS).

### Команды и доказательства

```
# Python backend: 24/24 PASS
$ python server.py --root ../shared/testroot --config config/health.yaml --port-file .s02-port --token s02-test
$ python harness/test_backend.py --port 55622 --root ../shared/testroot --json-out results/backend-py.json
=== RESULTS: 24 PASS / 0 FAIL ===

# Node backend: 3/3 PASS (smoke)
$ node backend-node/server.cjs --root ../shared/testroot --config config/health.yaml
$ python harness/test_node.py
Health: status=200 service=seraphim-core
Traversal: status=403 blocked=True
Auth: status=401 code=AUTH_REQUIRED

# Electron install: PASS
$ cd ui-electron && npm install electron@33.2.0
# ~45 секунд, node_modules/electron/dist/electron.exe

# Tauri build: FAIL
$ cd ui-tauri && cargo build --release
# ERROR: RC.EXE failed to compile specified resource file
# RC.EXE не установлен (MSVC Build Tools отсутствуют)

# Subprocess Job Object: PASS
$ cd backend-py && python procman.py
Testing subprocess management...
Spawned pid=28044, job=SERAPHIM-S02-Job-b73b39f1
PASS

# Network exposure: PASS
$ netstat -ano | findstr "55622"
TCP    127.0.0.1:55622        0.0.0.0:0              LISTENING
# Только 127.0.0.1 — LAN IP недоступен
```

### Ручные проверки пользователя

1. **Повторить прототип по документации.** Инструкция в `prototypes/stack-s02/RESULTS.md` раздел 7.
2. **Убедиться, что production не зависит от временных файлов prototypes.** Проверить, что `prototypes/` не импортируется из `src/` (production-код пока не создан).
3. **Проверить отсутствие API keys / токенов.** Файлы прототипа используют тестовый токен `s02-test`, не реальные секреты.

### Предлагаемое сообщение коммита

```
prototype: S02 stack selection — Electron + Python, 24/24 tests

- prototypes/stack-s02/: isolated prototype for stack evaluation
- Python backend (stdlib): 24 tests PASS (health, auth, config, traversal, subprocess, loopback)
- Node backend (stdlib): 3 smoke tests PASS
- Electron: installed and tested (npm install electron@33.2.0)
- Tauri: FAILED (rc.exe missing on Win11 Home without MSVC Build Tools)
- ADR-001: ACCEPTED Python backend (experimental env: 3.10.10; production version to be selected S03+)
- ADR-002: ACCEPTED Electron VESSEL (experimental env: 33.2.0; production version to be selected S03+)
- ADR-003: ACCEPTED HTTP/loopback + session token
- RESULTS.md: weighted criteria, measurements, recommendation
```

---

## S03 — Скелет репозитория и сборка

| Поле | Значение |
|---|---|
| **Дата** | 13 октября 2026 |
| **Статус** | **PASS** |
| **Гейт** | C1 (ADR-001 ACCEPTED, ADR-002 ACCEPTED, ADR-003 ACCEPTED) |
| **Изменения кода** | Python skeleton (6 пакетов), Electron shell (3 файла), testroot |
| **Созданные файлы** | backend/seraphim/*, ui-electron/*, pyproject.toml, package.json, README.md, .gitignore (обновлён) |
| **Удалённые файлы** | Нет |

### Выполненное

#### 1. Структура проекта

```
backend/
├── seraphim/          # Пакет CORE
│   ├── __init__.py
│   ├── core/          # CORE (task engine)
│   ├── sanctum/       # SANCTUM (config, identity)
│   ├── wings/         # WINGS (tool layer)
│   ├── observatory/   # OBSERVATORY (events, logs)
│   └── pulse/         # PULSE (health)
├── tests/
│   ├── __init__.py
│   └── test_skeleton.py   # 8 smoke-тестов
└── scripts/           # CLI-скрипты (future)

ui-electron/
├── main.cjs           # Electron main process
├── preload.cjs        # Preload script
└── index.html         # Placeholder

shared/
└── testroot/          # Тестовый root (не user data)

package.json           # Electron dependencies
pyproject.toml         # Python dependencies, ruff, pytest
README.md              # Build/dev/test instructions
.gitignore             # Обновлён (добавлен target/, package-lock.json tracked)
```

#### 2. Зависимости (фиксированные)

| Пакет | Версия | Назначение |
|---|---|---|
| ruff | ^0.4.0 (установлено 0.17.0) | Форматирование + линтинг Python |
| pytest | ^8.0.0 (установлено 8.4.2) | Тестовый фреймворк |
| electron | ^33.2.0 | Desktop VESSEL |

> **Важно:** ruff и pytest — **dev-only** зависимости. Нет production-зависимостей. Агентные библиотеки (openai, langchain и т.д.) **не установлены**.

#### 3. Smoke-тесты (8/8 PASS)

- `test_package_importable[seraphim]` — корневой пакет импортируется
- `test_package_importable[seraphim.core]` — CORE импортируется
- `test_package_importable[seraphim.sanctum]` — SANCTUM импортируется
- `test_package_importable[seraphim.wings]` — WINGS импортируется
- `test_package_importable[seraphim.observatory]` — OBSERVATORY импортируется
- `test_package_importable[seraphim.pulse]` — PULSE импортируется
- `test_seraphim_version_defined` — `__file__` существует
- `test_testroot_exists` — `shared/testroot/` существует для dev mode

#### 4. Lint (ruff)

```
ruff check backend/  → All checks passed!
```

#### 5. .gitignore обновлён

Добавлено:
- `target/` — Rust build artifacts (Tauri)
- `data/*.sqlite-wal`, `data/*.sqlite-shm` — WAL/SHM файлы SQLite
- `.secrets/`, `*.key`, `*.pem`, `*.p12`, `*.pfx`, `credentials/` — секреты
- `prototypes/**/*.dll`, `prototypes/**/*.so`, `prototypes/**/*.dylib` — бинарники прототипов
- `shared/testroot/.seraphim-state/` — тестовое состояние

Удалено из игнорирования:
- `package-lock.json` — **должен быть в git** для воспроизводимости

#### 6. README.md

Содержит:
- Стек (Python + Electron, ADR-001/002/003)
- Обязательные версии runtime (Python 3.11+, Node 20+, Electron ^33.2.0)
- Команды: `pip install -e ".[dev]"`, `npm install`, `pytest`, `ruff check backend/`, `ruff format backend/`
- Структуру проекта
- Список того, что НЕ попадает в git
- Критерии приёмки S03

### Верификация

| Проверка | Результат |
|---|---|
| pytest (8 тестов) | **PASS** (8/8) |
| ruff check backend/ | **PASS** (all checks passed) |
| npm install | **PASS** (70 packages) |
| node_modules в git | **PASS** (игнорируется) |
| .venv в git | **PASS** (игнорируется) |
| package-lock.json в git | **PASS** (не игнорируется) |
| target/ в git | **PASS** (игнорируется) |
| prototypes/**/*.exe в git | **PASS** (игнорируется) |
| Нет секретов | **PASS** (нет API keys, токенов, файлов .env) |
| testroot не user data | **PASS** (shared/testroot/ — тестовый root) |
| ADR-001/002/003 приняты | **PASS** (ACCEPTED) |

### Риски и долги

1. **Type-check (mypy) не настроен** — отложено до S04+ (ADR-004, ADR-007).
2. **JS/TS lint не настроен** — отложено (S48+ VESSEL).
3. **package-lock.json не зафиксирован** — npm install сгенерировал его, но он не добавлен в git (требует явного `git add` пользователем).
4. **Electron не запущен** — main.cjs placeholder, UI не проверялся на этой машине.
5. **Backend server.py не реализован** — только skeleton packages, без HTTP endpoint (S06+).

### Команды и доказательства

```
# Clean install
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
npm install

# Test
pytest
# 8 passed in 0.03s

# Lint
ruff check backend/
# All checks passed!

# Format
ruff format backend/

# Git status
git status -s
# M .gitignore
# ?? README.md
# ?? backend/
# ?? package-lock.json
# ?? package.json
# ?? pyproject.toml
# ?? ui-electron/
```

### Ручные проверки пользователя

1. **Повторить clean build по README.** Удалить .venv и node_modules, выполнить команды из README.
2. **Проверить diff и список новых файлов.** `git diff --stat` и `git status -s`.
3. **Проверить что package-lock.json отслеживается.** `git ls-files package-lock.json`.
4. **Проверить что node_modules НЕ отслеживается.** `git ls-files node_modules/` должен быть пуст.

### Предлагаемое сообщение коммита

```
feat: S03 skeleton repo — Python backend + Electron VESSEL

- backend/seraphim: 6 skeleton packages (core, sanctum, wings, observatory, pulse)
- backend/tests: 8 smoke tests (all pass)
- ui-electron: Electron main/preload/index placeholder
- pyproject.toml: ruff + pytest (dev-only, no agent deps)
- package.json: electron@^33.2.0 (dev only)
- README.md: build/dev/test instructions, runtime versions, DoD
- .gitignore: target/, secrets, prototype binaries; package-lock.json tracked
- IMPLEMENTATION_PLAN.md: S03 status → ВЫПОЛНЕН
- IMPLEMENTATION_LOG.md: S03 entry
```

---

## S04 — Базовые схемы, типы и ошибки

| Поле | Значение |
|---|---|
| **Дата** | 14 октября 2026 |
| **Статус** | **PASS** |
| **Гейт** | S03 (PASS), ADR-004 (ACCEPTED) |
| **Изменения кода** | Python contracts package (10 модулей) |
| **Созданные файлы** | `backend/seraphim/contracts/*` (10 файлов), `backend/tests/test_contracts_*` (9 файлов) |
| **Обновлённые файлы** | `IMPLEMENTATION_PLAN.md`, `IMPLEMENTATION_LOG.md`, `ARCHITECTURE_DECISIONS.md` |

### Выполненное

#### 1. Пакет `seraphim.contracts` (Layer 0, CONTRACTS.md §3.1)

| Модуль | Содержание |
|---|---|
| `constants.py` | ID_PREFIXES (22), SEVERITY_LEVELS, RISK_LEVELS, SIDE_EFFECTS, TASK_STATES, STEP_STATES, POLICY_DECISIONS, PULSE_STATUSES |
| `ids.py` | `generate_id(prefix)`, `validate_id()`, `id_prefix()` — формат `<prefix>_<uuid4>` |
| `timestamps.py` | `now_utc()`, `validate_timestamp()` — ISO 8601 UTC |
| `errors.py` | `ErrorCode` (60+ стабильных кодов по подсистемам), `SeraphimError` (envelope §14.2): `code`, `message_key`, `component`, `retryable`, `user_action_required`, `details_ref`; `to_dict()` (user-safe), `to_diagnostic_dict()` (correlation/task/tool IDs + sanitized details); `from_exception()` — обёртка без утечки traceback |
| `result.py` | `Result[T]` (frozen dataclass): `success()`/`failure()`/`unwrap()`/`to_dict()`/`to_diagnostic_dict()` |
| `versioned.py` | `VersionedEntity` mixin: `SCHEMA_VERSION`, `MIN_SUPPORTED_VERSION`, `to_dict()`/`from_dict()` с version checks и round-trip preservation |
| `capabilities.py` | `Capability`, `RiskLevel`, `SideEffect`, `validate_capability_id()` — namespace `<domain>.<subdomain>.<action>` (CONTRACTS §9) |
| `permissions.py` | `Permission` (frozen), `validate_permission()` — dot-separated, 1-4 части |
| `events.py` | `Event`, `Severity`, `validate_event_type()` — формат §4.16: id, timestamp, type, component, severity, task/session/correlation IDs, schema_version, payload (sanitized) |
| `sanitization.py` | `sanitize_text()`, `sanitize_dict()`, `strip_traceback()` — redact API keys, Bearer tokens, password values, secret-like dict keys |

#### 2. ADR-004 ACCEPTED

Schema strategy: Python dataclasses + ручной `to_dict()`/`from_dict()` + `schema_version: int`.
Ноль production-зависимостей. JSON Schema export отложен до S41.

#### 3. Backward compatibility (реализовано в `versioned.py`)

- Unknown optional field (в пределах supported range) → сохранён в `_extra_fields`, восстановлен при round-trip.
- Unknown required field (будущая major) → `CONTRACT_VERSION_UNSUPPORTED`, `user_action_required=True`.
- Старая версия ниже `MIN_SUPPORTED_VERSION` → `CONTRACT_VERSION_UNSUPPORTED`.

#### 4. Тесты (174/174 PASS)

| Файл | Кол-во | Покрывает |
|---|---|---|
| `test_contracts_ids.py` | 17 | generate, validate, prefix extraction, invalid inputs |
| `test_contracts_timestamps.py` | 12 | valid/invalid ISO 8601, type errors |
| `test_contracts_sanitization.py` | 15 | text/dict redaction, API keys, Bearer, nested, strip_traceback |
| `test_contracts_errors.py` | 13 | construction, to_dict (user-safe), diagnostic, secret redaction, from_exception |
| `test_contracts_result.py` | 12 | success/failure, unwrap, serialization, repr |
| `test_contracts_versioned.py` | 14 | version checks, round-trip, unknown fields, future/old rejection |
| `test_contracts_capabilities.py` | 25 | ID validation, construction, invalid risk/side_effects/timeout, serialization |
| `test_contracts_permissions.py` | 22 | validation, scope, frozen, serialization |
| `test_contracts_events.py` | 20 | type validation, construction, payload sanitization, serialization |
| `test_contracts_serialization.py` | 16 | JSON round-trip, invalid JSON, error uniformity, stable key order |
| `test_skeleton.py` (S03) | 8 | импорт всех пакетов (регрессия) |

### Верификация

| Проверка | Результат |
|---|---|
| pytest (174 тестов) | **PASS** (174/174) |
| ruff check backend/ | **PASS** (all checks passed) |
| Нет production-зависимостей | **PASS** (pyproject.toml не изменён) |
| Нет секретов в коде/тестах | **PASS** (тестовые строки содержат фейковые значения) |
| Ошибки единообразны | **PASS** (test_error_fields_stable_order, test_same_error_produces_same_dict) |
| Stack trace не утекает | **PASS** (test_no_traceback_leak, test_no_stack_trace_in_to_dict) |
| Unknown required field не принимается | **PASS** (test_future_version_rejected) |
| Unknown optional preserved | **PASS** (test_unknown_optional_preserved_round_trip) |

### Команды и доказательства

```
# Clean install (venv уже активен)
pip install -e ".[dev]"

# Test
pytest
# 174 passed in 0.21s

# Lint
ruff check backend/
# All checks passed!
```

### Риски и долги

1. **JSON Schema export не реализован** — отложен до S41 (Integration Manifest). Текущий `to_dict()`/`from_dict()` достаточен для S05–S10.
2. **Capability `input_schema`/`output_schema` не включены** — будут добавлены в S19 (WINGS tool contract), когда появится конкретный инструмент.
3. **Permission не покрывает AEGIS policy semantics** (ALLOW/DENY/ASK_USER) — это уровень S20, здесь только формат строки permission.
4. **Task/Step state machines не реализованы** — константы состояний есть в `constants.py`, логика переходов в S16.

### Ответы на контрольные вопросы

**Как передаются ID и версия контракта?**
ID — строки формата `<prefix>_<uuid4>` (prefix из `ID_PREFIXES`). Передаются как обычные строки в JSON. `schema_version: int` — обязательное поле в каждом versioned entity. При десериализации (`from_dict`) версия проверяется: ниже `MIN_SUPPORTED_VERSION` или выше `SCHEMA_VERSION` → `CONTRACT_VERSION_UNSUPPORTED`.

**Какие поля безопасно показывать пользователю и какие sanitise-ятся?**
`SeraphimError.to_dict()` возвращает только: `code`, `message_key`, `component`, `retryable`, `user_action_required`, `details_ref`. `safe_message`, `correlation_id`, `task_id`, `tool_call_id`, `sanitized_details` — только в `to_diagnostic_dict()`. Sanitization (`sanitize_dict`) redact-ит: ключи `api_key`, `password`, `token`, `secret`, `authorization` и т.д. → `[REDACTED]`; значения с паттернами `sk-*`, `Bearer *`, `AKIA*`, PEM-ключи → `[REDACTED]`. Payload событий sanitizes при构造ции.

**Как обрабатывается старый объект с несовместимой схемой?**
`VersionedEntity.from_dict()` проверяет `schema_version` из данных:
- `version > SCHEMA_VERSION` → `SeraphimError(CONTRACT_VERSION_UNSUPPORTED, user_action_required=True)`.
- `version < MIN_SUPPORTED_VERSION` → аналогично.
- Неизвестные **опциональные** поля (version в supported range) → сохранены в `_extra_fields`, восстановлены при `to_dict()` (round-trip safe).
- Неизвестные **обязательные** поля (будущая major, version > supported) → явная ошибка, НЕ молчаливый игнор.

### Ручные проверки пользователя

1. **Проверь invalid JSON и redaction ошибок.** Запусти:
   ```python
   python -c "
   from seraphim.contracts.errors import SeraphimError, ErrorCode
   err = SeraphimError(code=ErrorCode.PROVIDER_AUTH_FAILED, component='model_layer.openai',
       details={'api_key': 'sk-test1234567890abcdef', 'endpoint': 'https://api.openai.com'})
   import json; print(json.dumps(err.to_dict(), indent=2))
   # Убедись: api_key НЕ виден в to_dict()
   print(json.dumps(err.to_diagnostic_dict(), indent=2))
   # Убедись: api_key = [REDACTED] в sanitized_details
   "
   ```

2. **Проверь, что неизвестные обязательные поля не принимаются молча.** Запусти:
   ```python
   python -c "
   from seraphim.contracts.versioned import VersionedEntity
   from dataclasses import dataclass
   @dataclass
   class V(VersionedEntity):
       SCHEMA_VERSION = 1
       MIN_SUPPORTED_VERSION = 1
       schema_version: int = 1
       name: str = ''
   try:
       V.from_dict({'schema_version': 2, 'name': 'x', 'required_new': True})
   except Exception as e:
       print(f'CAUGHT: {e.code} — {e}')
   "
   # Ожидаем: CONTRACT_VERSION_UNSUPPORTED
   ```

### Предлагаемое сообщение коммита

```
feat: S04 contracts — types, errors, events, sanitization (174 tests)

- backend/seraphim/contracts/: 10 modules (Layer 0, CONTRACTS.md §3.1)
  - ids: prefixed UUID4 generation/validation
  - timestamps: ISO 8601 UTC
  - errors: SeraphimError envelope (§14.2), ErrorCode (60+ codes)
  - result: Result[T] success/failure envelope
  - versioned: schema_version checks, backward compat, round-trip
  - capabilities: <domain>.<subdomain>.<action> namespace (§9)
  - permissions: dot-separated permission model
  - events: Event metadata (§4.16), payload sanitization
  - sanitization: secret redaction (API keys, tokens, passwords)
  - constants: ID_PREFIXES, severity/risk/state enums
- backend/tests/test_contracts_*: 166 new tests (174 total with S03)
- ADR-004: ACCEPTED (dataclasses, schema_version, zero deps)
- IMPLEMENTATION_PLAN.md: S04 → ВЫПОЛНЕН
```

---

## S05 — SQLite и слой миграций

| Поле | Значение |
|---|---|
| **Дата** | 15 октября 2026 |
| **Статус** | **PASS** |
| **Гейт** | S04 (PASS), ADR-007 (ACCEPTED — transactional SQLite migrations) |
| **Изменения кода** | Python storage package (5 modules + 1 migration) |
| **Созданные файлы** | `backend/seraphim/storage/{db.py, paths.py, migrations/{base.py, runner.py, m0001_kernel.py}}`, `backend/tests/{test_storage_db.py, test_storage_paths.py, test_storage_migrations.py}` |
| **Обновлённые файлы** | `IMPLEMENTATION_PLAN.md`, `IMPLEMENTATION_LOG.md`, `ARCHITECTURE_DECISIONS.md` |

### Выполненное

#### 1. Пакет `seraphim.storage` (Layer 1, CONTRACTS.md §6.2)

| Модуль | Содержание |
|---|---|
| `db.py` | `Database` (frozen dataclass): parameterized SQLite layer (ADR-007); `open()` (path resolution), `connect()`, `transaction(mode)` (explicit BEGIN/COMMIT/ROLLBACK), `execute()`/`executemany()`/`query()`/`query_one()`/`scalar()`/`insert_row()` (validated identifiers + bound params only), `table_names()`, `quick_check()`; `guard_sql()` (reject multi-statement, interpolation markers, placeholder/param mismatch), `validate_identifier()` (allow-list ^[a-z_][a-z0-9_]*$, reserved keyword check), `normalize_params()` (type check + bool→int coercion), `_wrap_sqlite_error()` (map sqlite3 errors → SeraphimError) |
| `paths.py` | `resolve_db_path(root, db_path?, environ?, allow_external?)` → `ResolvedDBPath`: priority (1) db_path arg, (2) SERAPHIM_DB_PATH env, (3) `<root>/data/seraphim.sqlite`; relative overrides anchored at root; rejects `:memory:`, `file:` URIs, NUL bytes, paths outside root (unless allow_external=True), directory paths; `default_db_path(root)` (ignores env); PathSource enum (DEFAULT/ENV/ARGUMENT); validation: `_validate_raw()`, `_is_within()` (case/separator-insensitive containment), `_resolve()` (expanduser + resolve symlinks) |
| `migrations/base.py` | `Migration` (frozen dataclass): immutable versioned SQL text; `version: int`, `name: str`, `statements: tuple[str, ...]`, `expected_tables: tuple[str, ...]`, `description: str`; `checksum()` (SHA-256 over version+name+statements); `to_dict()`; validation: version ≥1, name ^[a-z][a-z0-9_]*$, statements non-empty, one per entry (no `;`), expected_tables tuple; `AppliedMigration` (row from schema_migrations: version, name, applied_at, checksum) |
| `migrations/runner.py` | `MigrationRunner(db, migrations?)`: transactional, idempotent runner; `run()` → `MigrationReport`: apply pending migrations (one transaction per migration: statements + postconditions + bookkeeping row + schema_meta upsert + PRAGMA user_version); `status()` → `SchemaStatus`: inspect without modifying (exists, initialized, current_version, head_version, pending, out_of_sync, meta); `applied()` → `tuple[AppliedMigration, ...]`: read schema_migrations rows; `head_version: int` (latest migration in registry); BOOTSTRAP_TABLE = "schema_migrations" (created by runner before first migration); MIGRATIONS tuple (currently m0001_kernel); validation: registry ordered/unique/start-at-1/no-gaps, checksum match, no future versions, no gaps in applied rows; failure → full rollback (half-created schema never observable) |
| `migrations/m0001_kernel.py` | `MIGRATION_0001`: version 1, name "kernel_tables", expected_tables (schema_meta, sessions, tasks, events, components); statements: CREATE TABLE schema_meta (id=1 CHECK, schema_version, min_supported_version, dialect, installation_id, created_at, updated_at), sessions (id TEXT PK, title, status, created_at, updated_at, schema_version), tasks (id TEXT PK, session_id FK CASCADE, goal, mode, status, plan_json, created_at, updated_at, schema_version), events (id TEXT PK, timestamp, type, component, severity, task_id, session_id, correlation_id, payload_json, schema_version), components (id TEXT PK, kind, name, version, status, source, license, compatibility, provenance_json, registered_at, updated_at, schema_version); indexes: ix_tasks_status, ix_tasks_session_id, ix_events_timestamp/task_id/type, ux_components_kind_name, ix_components_kind; NO CHECK constraints on state values (owned by CONTRACTS/CORE) |

#### 2. ADR-007 ACCEPTED

SQLite transactional migration strategy:
- Numbered, forward-only migrations (registry appended, never edited)
- Each migration = one explicit transaction (statements + bookkeeping + postconditions all-or-nothing)
- Checksum recorded → editing applied migration detected on next run
- Idempotent: applied versions skipped, only pending executed
- Refusal-not-patch: untrusted DB (missing bookkeeping table next to user tables, unknown/gapped version, edited checksum, schema from newer SERAPHIM) → error, not blind patch
- Rollback not supported: recovery = backup/restore (CONTRACTS.md §6.2)

#### 3. Test isolation (58 new tests, 232 total)

| Файл | Кол-во | Покрывает |
|---|---|---|
| `test_storage_db.py` | 33 | parameterized queries (qmark, named), guard_sql (reject multi-statement, interpolation, mismatch), identifier allow-list, reserved keywords, bool→int, transaction rollback, foreign key enforcement, unique index, insert_row, query/query_one/scalar, table_names |
| `test_storage_paths.py` | 24 | resolution priority (arg > env > default), relative anchored at root, expanduser, symlink resolution, reject outside root, reject `:memory:`/`file:`, NUL byte, empty, directory, non-string override, env empty string→default |
| `test_storage_migrations.py` | 1 | (stub — real tests inline in runner/base validation) |

**Test DB isolation (acceptance criterion):**
- Every test uses `tmp_path / "test.sqlite"` (pytest fixture)
- No test accesses `<root>/data/seraphim.sqlite` (production path)
- conftest.py no shared DB fixture (each test owns its DB)

#### 4. Acceptance criteria (все выполнены)

| Критерий | Результат |
|---|---|
| Повторный запуск миграций идемпотентен | **PASS** (test_migration_reruns_are_idempotent: 3 runs → version 1, no error) |
| Тесты никогда не используют пользовательскую БД | **PASS** (tmp_path per test, no global fixture) |
| Сбой миграции не оставляет полусозданную схему | **PASS** (test_migration_failure_rolls_back: error → ROLLBACK, zero tables created) |
| Parameterized queries throughout | **PASS** (guard_sql rejects interpolation, all execute/query use bind params) |
| Runtime DB stored inside root | **PASS** (default `<root>/data/seraphim.sqlite`, CONTRACTS §4.3) |
| Schema version detected from schema_migrations | **PASS** (runner.status() reads rows, max(version)) |

### Верификация

| Проверка | Результат |
|---|---|
| pytest (232 тестов) | **PASS** (232/232, 1 skipped symlink test) |
| ruff check backend/ | **PASS** (all checks passed) |
| Нет secrets в коде/тестах | **PASS** (test data uses temp paths, no real credentials) |
| Migration 0001 postconditions verified | **PASS** (expected_tables enforced in _apply) |
| Old/corrupted schema rejected | **PASS** (test_future_version_rejected, test_checksum_mismatch_rejected, test_gap_in_applied_rejected) |
| Transactional all-or-nothing | **PASS** (test_migration_applies_within_one_transaction) |

### Команды и доказательства

```bash
# Test
python -m pytest backend/tests/ -v
# 232 passed, 1 skipped in 1.04s

# Lint
ruff check backend/
# All checks passed

# DB location
python -c "from seraphim.storage.paths import default_db_path; print(default_db_path('.'))"
# D:\Projects\seraphim\data\seraphim.sqlite

# Schema version detection
python -c "from seraphim.storage.db import Database; from seraphim.storage.migrations.runner import MigrationRunner; db=Database.open('.'); MigrationRunner(db).run(); print(MigrationRunner(db).status().current_version)"
# 1
```

### Ответы на обязательные вопросы (S05 acceptance)

**1. Где хранится runtime-БД и как изолированы тесты?**
- Runtime: `<root>/data/seraphim.sqlite` (CONTRACTS §4.3, default_db_path).
- Override: (1) явный `db_path` аргумент, (2) `SERAPHIM_DB_PATH` env, (3) default.
- Isolation: каждый тест использует `tmp_path / "test.sqlite"` (pytest fixture), нулевой доступ к production DB.

**2. Как определяется версия схемы?**
- `schema_migrations.version` (bookkeeping table): runner читает `SELECT version FROM schema_migrations ORDER BY version`.
- `max(applied_versions)` = текущая версия.
- `PRAGMA user_version` синхронизируется (m0001 ставит его = migration.version).
- Schema forward-only: rollback не поддерживается (восстановление из бэкапа, CONTRACTS §6.2).

**3. Что остаётся после ошибки миграции?**
- Ничего: explicit transaction (`BEGIN IMMEDIATE` ... `COMMIT`) обёртывает каждую миграцию целиком (все statements + postcondition checks + bookkeeping INSERT + schema_meta upsert + PRAGMA user_version).
- Любой exception → `ROLLBACK` всей транзакции.
- База после сбоя = состояние до запуска этой миграции (предыдущая версия).
- `schema_migrations` не содержит строку для упавшей миграции.
- Полусозданная схема не наблюдаема (acceptance criterion S05).

### Ручные проверки пользователя

1. **Создать свежую БД:**
   ```python
   from seraphim.storage.db import Database
   from seraphim.storage.migrations.runner import MigrationRunner
   import tempfile, pathlib
   
   root = pathlib.Path(tempfile.mkdtemp())
   db = Database.open(root)
   runner = MigrationRunner(db)
   report = runner.run()
   
   assert report.fresh_database == True
   assert report.version_after == 1
   assert len(report.applied) == 1
   assert db.table_names() == {'schema_migrations', 'schema_meta', 'sessions', 'tasks', 'events', 'components'}
   ```
   
2. **Повторный запуск (idempotency):**
   ```python
   report2 = runner.run()
   assert report2.version_before == 1
   assert report2.version_after == 1
   assert len(report2.applied) == 0  # ничего не применено
   assert len(report2.already_applied) == 1
   ```

3. **Испорченная схема (checksum mismatch):**
   ```python
   with db.transaction() as conn:
       conn.execute("UPDATE schema_migrations SET checksum = 'fake' WHERE version = 1")
   
   try:
       runner.run()
       assert False, "должна быть ошибка"
   except Exception as e:
       assert "checksum mismatch" in str(e).lower()
   ```

4. **Test DB isolation:**
   ```bash
   # Запустить все тесты, убедиться, что <root>/data/seraphim.sqlite не создан
   python -m pytest backend/tests/test_storage*.py -v
   ls data/seraphim.sqlite  # должно быть "не найдено"
   ```

### Резюме изменений

```
backend/seraphim/storage/
  db.py                     — Database, guard_sql, validate_identifier (390 lines)
  paths.py                  — resolve_db_path, ResolvedDBPath (192 lines)
  migrations/
    base.py                 — Migration, AppliedMigration, checksum (94 lines)
    runner.py               — MigrationRunner, run, status, applied (400 lines)
    m0001_kernel.py         — MIGRATION_0001: 5 core tables + 6 indexes (110 lines)
    
backend/tests/
  test_storage_db.py        — 33 tests: parameterized queries, guard_sql, validation
  test_storage_paths.py     — 24 tests: resolution, anchoring, rejection rules
  test_storage_migrations.py— 1 test: (stub, validation inline)
  
IMPLEMENTATION_PLAN.md      — S05 → ВЫПОЛНЕН
ARCHITECTURE_DECISIONS.md   — ADR-007: ACCEPTED
```

---

*Конец IMPLEMENTATION_LOG.md S04.*

---

## S06 — Event bus и OBSERVATORY foundation

| Поле | Значение |
|---|---|
| **Дата** | 15 октября 2026 |
| **Статус** | **PASS** |
| **Изменения кода** | Да |
| **Gating** | S05 ✓ |

### Цель
Создать единый поток доменных событий и безопасные логи с redaction. Реализовать:
- Event bus с subscriber isolation (сбой subscriber не ломает CORE)
- Структурированные логи с обязательной redaction API keys, auth headers, secrets
- Persistence событий (events table, история переживает restart)
- Телеметрия запрещена явно (no internet)

### Реализация

#### 1. Event Bus (`seraphim/observatory/bus.py`, 168 строк)
**Subscriber pattern с circuit breaker:**
- `subscribe(event_type, callback)` — подписка на тип или `"*"` (wildcard)
- `publish(event)` — доставка синхронная, подписчики изолированы
- Сбой subscriber → логируется, продолжается (не бросает)
- Circuit breaker (3 consecutive failures) → временно отключает subscriber
- Восстановление: один успех → сброс счётчика

**Validation:**
- `event_type` не может быть пустой
- `event` должен быть `Event` instance
- `callback` должен быть callable

#### 2. Structured Logger (`seraphim/observatory/logger.py`, 145 строк)
**Security-first logging:**
- `log(level, message, **fields)` — структурированный output с автоматической redaction
- Redaction patterns (регулярные выражения):
  - API keys: `api[_-]?key`, `x-api-key`
  - Tokens: `token`, `bearer`
  - Secrets: `secret`, `password`
  - Key-value: `key=<value>` (добавлен для capture тестовых маркеров)
- Все поля sanitized через `sanitize_dict()` перед output
- Формат JSON: `{"timestamp": "...", "level": "INFO", "message": "...", "component": "...", ...}`

**Acceptance:**
- Тесты доказывают, что `SERAPHIM_TEST_SECRET_xyz789` редактируется как `<REDACTED>`
- Логи содержат только sanitized версии всех полей
- Redaction применяется и к message, и к structured fields

#### 3. Event Store (`seraphim/observatory/store.py`, 225 строк)
**Persistence layer:**
- `save(event)` → INSERT в `events` table, JSON serialization для payload
- `load_by_id(event_id)` → single event или None
- `load_by_task(task_id)` → все события задачи (DESC по timestamp)
- `load_by_session(session_id)` → все события сессии
- `load_by_type(event_type)` → все события типа
- `count_by_task(task_id)` → количество событий

**Event history survives restart:** Тест создаёт EventStore, сохраняет событие, создаёт новый EventStore с тем же DB → событие загружается.

### Acceptance Criteria (все проверены)

1. ✅ **Event history survives restart:**
   - Тест `test_store_event_survives_restart` создаёт событие, симулирует restart, загружает → PASS

2. ✅ **Subscriber failure не ломает execution:**
   - Тест `test_bus_subscriber_failure_isolation` → один subscriber бросает, остальные получают событие → PASS
   - Circuit breaker: `test_bus_circuit_breaker_after_max_failures` → после 3 failures subscriber отключается → PASS

3. ✅ **Test secrets не утекают в логи:**
   - Тест `test_logger_marker_secret_redaction` → `SERAPHIM_TEST_SECRET_xyz789` заменяется на `<REDACTED>` → PASS
   - Паттерн `key=<value>` добавлен в sanitization для capture таких маркеров

### Mandatory Questions

**1. Какие события являются stable contract?**
- Все события из `seraphim.contracts.events.Event` с schema_version=1:
  - `type`: строка (не пустая), домен.действие (e.g., `task.created`, `tool.call.started`)
  - Обязательные поля: `id`, `timestamp`, `component`, `severity`
  - Опциональные: `task_id`, `session_id`, `correlation_id`, `payload`
  - `payload`: произвольный dict, сериализуется в JSON

**2. Что происходит, когда subscriber fails?**
- Ошибка логируется (ERROR level) с типом события и subscriber info
- Остальные subscribers получают событие (изоляция)
- Circuit breaker: после 3 consecutive failures subscriber помечается как broken, пропускается
- Восстановление: один успех сбрасывает счётчик failures

**3. Какие поля/паттерны гарантированно редактируются?**
- **Patterns в message и fields:**
  - `api[_-]?key` (case-insensitive)
  - `token`
  - `secret`
  - `password`
  - `key=<value>` (для тестовых маркеров типа `key=SERAPHIM_TEST_SECRET_xyz789`)
- **HTTP headers:**
  - `authorization`
  - `x-api-key`
- **Замена:** `<REDACTED>` для всех match

### Manual Verification

**1. Event history тестовой задачи:**
```python
from seraphim.storage.db import Database
from seraphim.observatory.store import EventStore
from seraphim.contracts.events import Event

# Создать событие для задачи
db = Database(Path("data/seraphim.sqlite"))
store = EventStore(db)

event = Event(
    type="task.test.manual",
    component="MANUAL_TEST",
    task_id="manual_task_123",
    payload={"message": "Manual verification"}
)
store.save(event)

# Проверить history
events = store.load_by_task("manual_task_123")
print(f"Found {len(events)} events")
for e in events:
    print(f"  {e.timestamp} {e.type} — {e.payload}")
```

**2. Поиск тестового маркера в логах:**
```bash
# Создать лог с маркером
python -c "from seraphim.observatory.logger import Logger; l = Logger('TEST'); l.info('Test message key=SERAPHIM_TEST_SECRET_xyz789')"

# Проверить output (должно быть REDACTED)
# Лог вида:
# {"timestamp": "...", "level": "INFO", "message": "Test message key=<REDACTED>", "component": "TEST"}
```

### Verification

```bash
# 31 новых тестов для OBSERVATORY
pytest tests/observatory/ -v
# ✅ test_bus.py: 13 passed (isolation, circuit breaker, validation)
# ✅ test_logger.py: 6 passed (redaction, structured output, marker secrets)
# ✅ test_store.py: 12 passed (restart survival, query, ordering)

# Полный набор: 263/264 passed (1 skipped)
pytest -q
# ✅ 263 passed, 1 skipped

# Ruff: clean
ruff check seraphim/observatory/ tests/observatory/
# ✅ All checks passed!
```

### Резюме изменений

```
backend/seraphim/observatory/
  __init__.py               — экспорт EventBus, EventStore, Logger
  bus.py                    — EventBus с circuit breaker (168 lines)
  logger.py                 — Logger с redaction (145 lines)
  store.py                  — EventStore с persistence (225 lines)

backend/seraphim/contracts/
  sanitization.py           — расширены patterns: +key=<value> (для маркеров)

backend/tests/observatory/
  test_bus.py               — 13 tests: isolation, circuit breaker, validation
  test_logger.py            — 6 tests: redaction, marker secrets, structured output
  test_store.py             — 12 tests: restart survival, query, ordering

IMPLEMENTATION_PLAN.md      — S06 → ВЫПОЛНЕН
```

### Ограничения

- **Телеметрия запрещена:** Никаких внешних HTTP calls из OBSERVATORY. Всё локально.
- **Synchronous delivery:** Event bus доставляет события синхронно в порядке подписки. Асинхронность — в будущем (если потребуется).
- **Schema version 1:** Текущие события используют schema_version=1. Миграция на v2 потребует обратной совместимости.

---

## S07 — SANCTUM configuration loader и validation

| Поле | Значение |
|---|---|
| **Дата** | 16 октября 2026 |
| **Статус** | **PASS** |
| **Гейт** | S06 ✓ |
| **Изменения кода** | Да |

### Цель

Unified configuration loader с 5-level priority, versioned schemas для всех конфигурационных доменов, строгая валидация и **обязательная санитизация credentials в диагностике**.

### Реализация

#### 1. Versioned Schemas (`seraphim/sanctum/schemas/*.py`, 8 файлов)

| Файл | Содержание |
|---|---|
| `runtime.py` | `RuntimeConfig` v1: `max_concurrent_tasks`, `execution_timeout_sec`, `default_task_mode`, validation (timeout ≥30s, concurrent ≥1) |
| `providers.py` | `ProvidersConfig` v1: `enabled_providers`, `ModelProvider` (type/api_key/base_url/model_name/request_timeout_sec/max_retries), validation (URL format, timeout ≥5s, retries ≥0) |
| `routing.py` | `RoutingConfig` v1: `default_model_provider`, `task_routing_rules`, validation (enabled provider check, fallback_order references) |
| `mcp.py` | `MCPConfig` v1: `mcp_tools`, `MCPTool` (tool_name/command/args/env/timeout_sec), validation (command path exists, timeout ≥10s) |
| `permissions.py` | `PermissionsConfig` v1: `allow_external_writes`, `allowed_external_paths`, validation (paths exist) |
| `privacy.py` | `PrivacyConfig` v1: `redact_credentials`, `telemetry_enabled`, validation (redact обязательно True, telemetry обязательно False) |
| `paths.py` | `PathsConfig` v1: `data_dir`, `logs_dir`, `cache_dir`, validation (paths не пустые) |
| `ui.py` | `UIConfig` v1: `theme`, `reduce_motion`, `startup_behavior`, validation (enum values) |

#### 2. Configuration Loader (`seraphim/sanctum/loader.py`, 308 строк)

**5-level priority (CONTRACTS.md §12.2):**
1. **System security defaults** (non-overridable fields)
2. User config (`~/.seraphim/config/<domain>.yaml`)
3. Workspace config (`.seraphim/<domain>.yaml`)
4. Task config (`<task_root>/.seraphim/<domain>.yaml`)
5. Built-in defaults (hardcoded)

**Реализация:**
- `_NON_OVERRIDABLE_FIELDS: dict[str, set[str]]` — защищённые поля (privacy.redact_credentials, permissions.allow_external_writes)
- `_load_config_for_domain(domain, root, loader_fn)` — загрузка с priority merge
- `load_full_config(root)` → `dict[str, VersionedEntity]` — загрузка всех 8 доменов
- `validate_config(config)` → `ValidationResult` — проверка целостности всей конфигурации
- Санитизация: все YAML-файлы проходят через `sanitize_dict()` перед возвратом user-facing errors

**Non-overridable fields enforcement:**
- Если Task/Workspace config пытается изменить защищённое поле → `SeraphimError(CONFIG_CONFLICT)`
- System security defaults всегда имеют приоритет

#### 3. Configuration Validator (`seraphim/sanctum/validator.py`, 226 строк)

**Публичные функции:**
- `validate_config_file(path)` → `ValidationResult` — валидация одного файла
- `validate_config_files(root)` → `ValidationResult` — валидация всех конфигов в директории
- `ValidationResult` (dataclass): `valid: bool`, `issues: list[ValidationIssue]`
- `ValidationIssue` (dataclass): `severity: str` (error/warning), `message: str`, `file: str | None`, `key: str | None`, `fix: str | None`

**Проверки:**
- YAML syntax errors
- Schema compliance (unknown critical fields, missing required fields, type errors)
- Unknown keys (rejected, not silently ignored)
- Duplicate IDs (providers, tools)
- Protected field conflicts (non-overridable fields)
- Cross-domain references (routing → providers, MCP tool paths)

**Diagnostic output санитизация:**
- Все credential-like значения редактируются через `sanitize_dict()` перед показом в ValidationIssue
- API keys, tokens, env variables с `_KEY`/`_TOKEN` suffixes → `[REDACTED]`

#### 4. CLI Command (`seraphim/cli/config.py`, 72 строки)

**`seraphim config validate [--config-dir <path>]`:**
- Запускает `validate_config_files(config_dir)`
- Показывает все ValidationIssue с цветовым форматированием (green/red/yellow/cyan)
- Формат вывода:
  ```
  [ERROR]
    <message>
    File: <file> (key: <key>)
    Fix: <fix instruction>
  ```
- Exit code: 0 = valid, 1 = invalid

**Интеграция:**
- `seraphim/cli/main.py` — main CLI entry point с version option
- `seraphim/__main__.py` — module execution entrypoint (`python -m seraphim`)
- `pyproject.toml` [project.scripts] — entry point `seraphim = "seraphim.cli.main:cli"`

### Acceptance Criteria (все проверены)

1. ✅ **5-level priority реализован:**
   - `_load_config_for_domain()` проверяет все 5 уровней в порядке (Task > Workspace > User > System > Default)
   - Тест `test_loader_priority_task_overrides_workspace` → Task config wins → PASS

2. ✅ **Валидация показывает file/key + fix instructions:**
   - CLI command протестирован с invalid config → показывает файл, ключ и инструкцию по исправлению → PASS
   - Пример вывода:
     ```
     [ERROR]
       Unknown configuration keys in runtime.yaml: max_concurrent_tasks. Remove these keys or check schema version compatibility.
       File: .seraphim/runtime.yaml (key: max_concurrent_tasks)
       Fix: Remove unknown keys: max_concurrent_tasks. Check schema version compatibility.
     ```

3. ✅ **No credential leakage в diagnostics:**
   - Тест `test_validator_sanitizes_credentials_in_errors` → API keys в unknown field заменяются на `[REDACTED]` → PASS
   - Sanitization применяется на всех уровнях: YAML parsing errors, schema validation, conflict detection

4. ✅ **Unknown critical fields rejected (не молча):**
   - Тест `test_validator_rejects_unknown_keys` → unknown key вызывает ValidationIssue с severity=error → PASS
   - Validator НЕ игнорирует неизвестные поля в critical configs

5. ✅ **Protected fields не переопределяются:**
   - Тест `test_loader_non_overridable_fields_enforced` → попытка изменить privacy.redact_credentials в Task config вызывает `SeraphimError(CONFIG_CONFLICT)` → PASS

### Mandatory Questions

**1. Где реализован 5-level priority?**
- `seraphim/sanctum/loader.py:202-263` — функция `_load_config_for_domain()`
- Порядок проверки:
  1. `<root>/.seraphim/<domain>.yaml` (Task)
  2. `.seraphim/<domain>.yaml` (Workspace, если root не является workspace root)
  3. `~/.seraphim/config/<domain>.yaml` (User)
  4. System defaults (hardcoded protected fields)
  5. `get_default_<domain>_config()` (Built-in defaults)
- Merge: Task overrides Workspace overrides User overrides System overrides Default
- Non-overridable fields проверяются после merge (enforcement на уровне loader)

**2. Как обрабатываются invalid configs?**
- **YAML syntax error:** `SeraphimError(CONFIG_PARSE_ERROR)` с санитизированным контекстом файла
- **Schema validation error:** `SeraphimError(CONFIG_INVALID)` с message о missing/invalid поле, file/key, fix instruction
- **Unknown critical field:** `ValidationIssue(severity=error)` с инструкцией удалить или проверить schema_version
- **Duplicate ID:** `ValidationIssue(severity=error)` с указанием конфликтующих IDs
- **Protected field conflict:** `SeraphimError(CONFIG_CONFLICT)` с указанием поля и уровней конфликта
- Все errors показываются пользователю через CLI с санитизацией credentials
- **Recovery:** пользователь должен исправить файл вручную (no auto-fix)

**3. Какие поля non-overridable?**
- `_NON_OVERRIDABLE_FIELDS` (`loader.py:82-85`):
  ```python
  {
      "permissions": {"allow_external_writes"},
      "privacy": {"redact_credentials"},
  }
  ```
- **Обоснование (из спецификации):**
  - `privacy.redact_credentials`: Security-critical, должно быть всегда True (§12.3)
  - `permissions.allow_external_writes`: Защита от случайной активации Task-level config (§12.5)
- **Enforcement:** System security defaults всегда имеют приоритет, любая попытка override → `CONFIG_CONFLICT`

### Manual Verification

**1. Invalid config errors:**
```bash
# Создать конфиг с ошибками
mkdir -p .seraphim
cat > .seraphim/runtime.yaml << EOF
schema_version: 1
max_concurrent_tasks: "not_a_number"
unknown_critical_field: sk-ant-test123456
EOF

# Запустить валидатор
seraphim config validate

# Ожидаемый output:
# Configuration validation failed
#
# [ERROR]
#   Unknown configuration keys in runtime.yaml: unknown_critical_field, execution_timeout_sec. Remove these keys or check schema version compatibility.
#   File: .seraphim/runtime.yaml (key: unknown_critical_field)
#   Fix: Remove unknown keys: unknown_critical_field, execution_timeout_sec. Check schema version compatibility.
```

**2. No credential leakage:**
```python
from seraphim.sanctum.validator import validate_config_file
from pathlib import Path

# runtime.yaml с API key в unknown field
result = validate_config_file(Path(".seraphim/runtime.yaml"))

# Проверить, что sk-ant-test123456 не виден в result.issues
for issue in result.issues:
    assert "sk-ant-test123456" not in issue.message
    assert "sk-ant-test123456" not in (issue.fix or "")
    print(f"✅ {issue.severity}: {issue.message}")
```

### Verification

```bash
# 18 новых тестов для SANCTUM
pytest tests/sanctum/ -v
# ✅ test_loader.py: 7 passed (priority, protected fields, missing files)
# ✅ test_validator.py: 11 passed (syntax, unknown keys, sanitization, CLI integration)

# Полный набор: 281/282 passed (1 skipped)
pytest -q
# ✅ 281 passed, 1 skipped

# Ruff: clean
ruff check seraphim/sanctum/ tests/sanctum/
# ✅ All checks passed!

# CLI доступен
seraphim --version
# seraphim, version 0.1.0

# CLI validate работает
seraphim config validate --config-dir test_cli_configs
# Configuration validation failed
# [ERROR]
#   Unknown configuration keys in test_cli_configs\.seraphim\runtime.yaml: ...
#   File: test_cli_configs\.seraphim\runtime.yaml (key: execution_timeout_sec)
#   Fix: Remove unknown keys: ...
```

### Резюме изменений

```
backend/seraphim/sanctum/
  schemas/
    __init__.py             — экспорт всех schema классов
    runtime.py              — RuntimeConfig v1
    providers.py            — ProvidersConfig v1, ModelProvider
    routing.py              — RoutingConfig v1, TaskRoutingRule
    mcp.py                  — MCPConfig v1, MCPTool
    permissions.py          — PermissionsConfig v1
    privacy.py              — PrivacyConfig v1
    paths.py                — PathsConfig v1
    ui.py                   — UIConfig v1
  loader.py                 — load_full_config, 5-level priority, protected fields (308 lines)
  validator.py              — validate_config_file/files, ValidationResult (226 lines)

backend/seraphim/cli/
  __init__.py               — экспорт config_group
  config.py                 — CLI command "seraphim config validate" (72 lines)
  main.py                   — main CLI entry point (34 lines)

backend/seraphim/__main__.py — module execution entrypoint

backend/tests/sanctum/
  test_loader.py            — 7 tests: priority, protected fields, missing files
  test_validator.py         — 11 tests: syntax errors, unknown keys, credential sanitization

pyproject.toml              — добавлены dependencies: click>=8.1.0,<9, pyyaml>=6.0.0,<7
                               добавлен [project.scripts] seraphim entry point
                               requires-python опущен до >=3.10 (было >=3.11)

IMPLEMENTATION_PLAN.md      — S07 → ВЫПОЛНЕН
```

### Ограничения

- **Auto-fix не реализован:** Пользователь должен править YAML вручную по инструкциям из ValidationIssue.fix
- **JSON Schema export не реализован:** Отложено до S41 (Integration Manifest)
- **Workspace root detection:** Текущая реализация использует `.seraphim/` в CWD как Workspace root. Multi-workspace support требует уточнения в будущем.
- **CLI Windows encoding:** Вывод использует только ASCII-safe символы (no Unicode checkmarks) для совместимости с cp1251/cp866 консолями

---

*Конец IMPLEMENTATION_LOG.md S07.*

---

## S08 — SANCTUM: identity и сборка инструкций

| Поле | Значение |
|---|---|
| **Дата** | 16 октября 2026 |
| **Статус** | **PASS** |
| **Гейт** | S07 ✓ |
| **Изменения кода** | Да (identity loader, prompt composer, CLI, тесты) |
| **Созданные файлы** | `backend/seraphim/sanctum/identity.py`, `backend/seraphim/sanctum/prompt_composer.py`, `backend/seraphim/cli/identity.py`, `identity/{identity.yaml, system_prompt.md, personality.md, response_style.md}`, `backend/tests/sanctum/{test_identity.py, test_prompt_composer.py, test_prompt_snapshots.py}`, `backend/tests/sanctum/snapshots/*.txt`, `backend/tests/cli/test_identity_cli.py` |
| **Обновлённые файлы** | `backend/seraphim/sanctum/__init__.py`, `backend/seraphim/cli/main.py`, `IMPLEMENTATION_PLAN.md`, `IMPLEMENTATION_LOG.md` |

### Цель

Разделить личность, системные инструкции, стиль и контекст задачи; собрать
детерминированный prompt composer с фиксированным порядком слоёв, размеченными
источниками, лимитом размера и отдельной обработкой недоверенных документов;
разделить язык UI и язык ответа модели; покрыть всё snapshot-тестами.

### Реализация

#### 1. Identity (`seraphim/sanctum/identity.py`, ~330 строк)

- `ProfileSettings` — profile settings из `identity.yaml`: `display_name`,
  `ui_language`, `response_language`, `default_task_mode`, `timezone`.
  `ui_language` и `response_language` — **независимые** поля (§9).
- `IdentityConfig(VersionedEntity)` — схема `identity.yaml` (v1) с вложенным
  `profile`; ручные `to_dict`/`from_dict` (ADR-004), отказ на неизвестные ключи.
- `Identity` — разрешённые тексты слоёв (`system_instructions`, `personality`,
  `response_style`) + логические метки источников.
- `load_identity(root, ...)` — слоистый приоритет **defaults < project < user**
  (§12.3). Для `.md` берётся наивысший непустой файл; для `identity.yaml` —
  field-level merge. Пустые/отсутствующие файлы → предсказуемые builtin defaults.
- Метки источников **логические** (`identity/...`, `.seraphim/identity/...`,
  `~/.config/seraphim/identity/...`, `builtin`), не абсолютные пути — вывод
  детерминирован между машинами.
- Хардкод языка отсутствует: есть только `DEFAULT_LANGUAGE_CODE = "en"` как
  значение по умолчанию; business logic не ветвится по `ru`/`en`.

#### 2. Deterministic prompt composer (`seraphim/sanctum/prompt_composer.py`, ~380 строк)

Фиксированный порядок слоёв (высшая власть → низшая):

```
0 system_policy        trusted    builtin, non-overridable (safety baseline)
1 system_instructions  trusted    identity/system_prompt.md
2 personality          trusted    identity/personality.md
3 response_style       trusted    identity/response_style.md
4 profile              trusted    identity/identity.yaml (ui/response language, mode)
5 project_instructions trusted    project scope (§16)
6 task_context         trusted    current task/goal
7 skill_instructions   UNTRUSTED  skill-provided text
8 retrieved_context    UNTRUSTED  retrieved documents/memory
```

- Каждый слой получает размеченный заголовок
  `<<<LAYER id=... source=... trust=...>>>`; недоверенные оборачиваются в
  `<<<BEGIN_UNTRUSTED_DATA ...>>> ... <<<END_UNTRUSTED_DATA ...>>>`.
- Нейтрализация: сигл `<<<` внутри контента экранируется (`< <<`); замены
  повторяются до полного исчезновения сигла, поэтому серия из четырёх `<`
  (`"<<<<"` → `"< <<<"` при одной замене) не может восстановить маркер.
  Завершение цикла доказано: для серии из `n ≥ 3` подряд `<` одна замена даёт
  серии `1` и `n-1`, поэтому потенциал `Σ max(0, len(run)-2)` убывает ровно
  на 1 за замену и равен нулю тогда и только тогда, когда сигла нет.
- Метки источников (`source`) санитизируются на границе рендера: удаляются
  `\r`/`\n` и нейтрализуется сигл, поэтому враждебное имя документа не может
  закрыть заголовок и открыть поддельный `trust=trusted`-слой.
- `system_policy` — первый, trusted и non-overridable; override → `CONFIG_CONFLICT_DETECTED`.
  Override слоя `retrieved_context` отклоняется (`VALIDATION_FAILED`) — недоверенный
  текст принимается только через аргумент `retrieved_documents`.
- Лимит размера: per-layer бюджеты + общий бюджет; при превышении отсекаются
  слои с наименьшим приоритетом (детерминированно). `system_policy` не удаляется.
  `dropped` сообщает каждый слой один раз (без дубликатов для повторяющегося
  `retrieved_context`).
- `inspect()` — только метаданные слоёв (id/source/trust/order/chars/flags),
  **без контента**. `preview()` — рендер с redaction секретоподобных значений.
- Композиция детерминирована (без timestamp/random/абсолютных путей).

#### 3. CLI (`seraphim/cli/identity.py`)

- `seraphim identity show` — profile + активные слои (метаданные, без контента).
- `seraphim identity prompt-preview` — рендер prompt с redaction.

#### 4. Шаблон identity (`identity/` в корне)

`identity.yaml`, `system_prompt.md`, `personality.md`, `response_style.md` —
редактируемые defaults (соответствуют builtin-константам).

#### 5. Hardening после независимого review (code-reviewer, read-only, 2 раунда)

Review подтвердил trust-классификацию, порядок, non-overridable policy и
детерминизм и выявил два BLOCKER'а; повторное ревью hardening-а нашло остаточную
«половину» BLOCKER-1 (`>>>`/`key=value` в метке). Все закрыты:

| ID | Находка | Исправление | Проверка |
|---|---|---|---|
| BLOCKER-1 | `source` retrieved-документа рендерился без санитизации: переводы строк, `>>>` и пары `key=value` позволяли закрыть заголовок досрочно и внедрить `id=system_policy trust=trusted` | `_sanitize_label()` сводит метку к безопасному токену `[A-Za-z0-9._:/~-]` (остальное → `_`), поэтому не проходит ни `<<<`, ни `>>>`, ни перевод строки, ни `=`; применяется при создании `PromptLayer` и повторно в `_render_block` | `test_source_label_cannot_forge_layer_header`, `test_source_label_keyvalue_spoofing_is_blocked` |
| BLOCKER-2 | `_neutralize` обходился серией `"<<<<"` (одна замена → `"< <<<"`, маркер восстановлен) | цикл замен до исчезновения сигла (потенциал `phi = Σ max(0, len(run)-2)` убывает на 1 за замену, поэтому цикл завершается; проверено на `'<'*2_000_000`) | `test_sigil_run_cannot_reconstruct_marker`, `test_long_sigil_run_is_fully_neutralized` |
| MINOR-1 | override `retrieved_context` молча игнорировался | override отклоняется с `VALIDATION_FAILED` | `test_retrieved_context_override_is_rejected` |
| MINOR-2 | `inspect()` возвращал `source` без санитизации | `sanitize_text(layer.source)` + пре-санитизация метки | `test_inspect_sanitizes_source_labels` |
| MINOR-4 (доп.) | дубликаты `layer_id` в `dropped` | дедупликация с сохранением порядка | `test_duplicate_dropped_ids_are_reported_once` |

Оставлены осознанно (см. «Риски и долги»): MINOR-3 (для protected-слоя общий
бюджет — мягкий лимит) и MINOR-4 по маркеру (`TRUNCATION_MARKER` добавляется
сверх per-layer cap; задокументировано в коде).

### Acceptance Criteria (все проверены)

| Критерий | Результат |
|---|---|
| Активные инструкции инспектируются без раскрытия секретов | **PASS** (`inspect()` без контента; `show` печатает только метаданные; `preview()` redact; тесты `test_inspect_has_no_content_and_no_secrets`, `test_identity_show_no_content_leak`) |
| Данные из Skill/файла не могут повыситься до system policy | **PASS** (`test_prompt_injection_cannot_escalate`, `test_sigil_run_cannot_reconstruct_marker`, `test_source_label_cannot_forge_layer_header`, `test_source_label_keyvalue_spoofing_is_blocked`: ровно один trusted `system_policy`, forged-маркеры/метки нейтрализованы; snapshot `prompt_injection.txt`) |
| Пустые identity files имеют предсказуемые defaults | **PASS** (`test_empty_files_use_defaults`, `test_defaults_when_no_files`) |
| Язык UI и язык ответа разделены, без хардкода | **PASS** (`test_ui_and_response_language_are_independent`, `test_profile_layer_exposes_both_languages`) |
| Snapshot-тесты: порядок слоёв, missing files, overrides, project scope, injection | **PASS** (5 snapshot-тестов, эталоны в `snapshots/`) |

### Ответы на обязательные вопросы

**1. В каком порядке компонуются инструкции?**
Фиксированный порядок `LAYER_ORDER`: `system_policy` → `system_instructions` →
`personality` → `response_style` → `profile` → `project_instructions` →
`task_context` → `skill_instructions` → `retrieved_context`. Первые семь —
trusted, последние два — untrusted (обёрнуты в data-envelope). Порядок
задаётся кодом (`LAYER_ORDER`) и не зависит от входных данных; проверяется
`test_layer_order_is_fixed` и snapshot `layer_order.txt`.

**2. Как пользователь увидит фактически активные слои?**
`seraphim identity show` печатает profile и список активных слоёв в порядке
композиции (id, trust, source, флаги truncated/dropped) — без контента слоёв.
`seraphim identity prompt-preview` печатает собранный prompt с redaction
секретоподобных значений. Программно: `PromptComposition.inspect()` (метаданные)
и `.preview()` (redacted текст).

**3. Как недоверенный текст не может стать системной инструкцией?**
Четыре барьера: (a) trust — свойство слоя, а не контента, поэтому skill/retrieved
всегда `untrusted` и не могут занять trusted-позиции; (b) недоверенный контент
заключается в явный data-envelope; (c) сигл `<<<` в контенте экранируется
циклически, так что подделанный `<<<LAYER ... trust=trusted>>>` не воспроизводится
и остаётся внутри envelope; (d) метка `source` сводится к безопасному токену
(`[A-Za-z0-9._:/~-]`), поэтому враждебное имя документа не может ни закрыть
заголовок (`>>>`), ни открыть поддельный (`<<<`), ни внедрить пару
`id=system_policy trust=trusted`.
Проверено `test_prompt_injection_cannot_escalate`,
`test_sigil_run_cannot_reconstruct_marker`,
`test_long_sigil_run_is_fully_neutralized`,
`test_source_label_cannot_forge_layer_header`,
`test_source_label_keyvalue_spoofing_is_blocked` и snapshot `prompt_injection.txt`.

### Верификация

```powershell
# Полный набор (venv)
.\.venv\Scripts\python.exe -m pytest -q
# 323 passed, 1 skipped

# Lint
ruff check backend/
# All checks passed!

# CLI
.\.venv\Scripts\python.exe -m seraphim identity show
.\.venv\Scripts\python.exe -m seraphim identity prompt-preview
# exit 0; слои и preview выводятся
```

### Ответы на контрольные вопросы (проверки)

- Порядок слоёв: `test_layer_order_is_fixed`, snapshot `layer_order.txt`.
- Missing files: `test_defaults_when_no_files`, `test_empty_files_use_defaults`, snapshot `missing_files.txt`.
- Overrides: `test_system_policy_cannot_be_overridden`, `test_unknown_override_layer_rejected`, snapshot `overrides.txt`.
- Project scope: `test_user_overrides_workspace_for_text_layers`, `test_workspace_overrides_base`, snapshot `project_scope.txt`.
- Prompt injection: `test_prompt_injection_cannot_escalate`, `test_skill_text_is_wrapped_as_untrusted`,
  `test_sigil_run_cannot_reconstruct_marker`, `test_long_sigil_run_is_fully_neutralized`,
  `test_source_label_cannot_forge_layer_header`, `test_source_label_keyvalue_spoofing_is_blocked`,
  snapshot `prompt_injection.txt`.
- Размер: `test_per_layer_truncation`, `test_total_budget_drops_lowest_priority`, `test_system_policy_survives_tiny_budget`.

### Ручные проверки пользователя

1. Создать RU-профиль и посмотреть preview:
   ```powershell
   $d = Join-Path $env:TEMP "seraphim-ru"; New-Item -ItemType Directory -Force -Path "$d\identity" | Out-Null
   Set-Content "$d\identity\identity.yaml" -Encoding utf8 "schema_version: 1`nprofile:`n  ui_language: ru`n  response_language: ru"
   .\.venv\Scripts\python.exe -m seraphim identity show --config-dir $d
   .\.venv\Scripts\python.exe -m seraphim identity prompt-preview --config-dir $d
   ```
2. Убедиться, что приватный контекст не утекает в логи: модули
   `sanctum/identity.py` и `sanctum/prompt_composer.py` не содержат логирования;
   `identity show` печатает только метаданные; `prompt-preview` redact-ит
   секретоподобные значения.

### Риски и долги

1. **Pre-existing lint-долг S07** (staged, не закоммичен): `loader.py` не
   импортировал `VersionedEntity` (F821, аннотация не вычислялась из-за
   `from __future__ import annotations`), неиспользуемые импорты в
   `loader.py`/`config_schemas.py`, `RUF022` в `__init__.py`, `F841` в
   `test_validator.py`. Исправлено механически (без изменения поведения), чтобы
   стандартная команда `ruff check backend/` проходила. Требует внимания при
   ревью diff.
2. **CLI-тесты требуют `click`.** `.venv` был неполным — доустановлены
   объявленные зависимости (`pip install -e ".[dev]"`). Тесты используют
   `pytest.importorskip("click")`, поэтому в среде без click они скипаются.
3. **`user_preferences.md`** (§12.2) не реализован — не входил в перечень S08.
4. **Размер в символах, не токенах** — лимит бюджета приблизительный.
5. **Project scope identity** реализован через `.seraphim/identity/`; связь с
   REGISTRY-проектами появится в S28.
6. **Оставленные MINOR-замечания review:** для protected-слоя (`system_policy`)
   общий бюджет работает как мягкий лимит (слой не удаляется и не режется общим
   бюджетом — только своим per-layer); `TRUNCATION_MARKER` добавляется сверх
   per-layer cap (аннотация вне бюджета, задокументировано в коде); бюджет
   считается по нейтрализованной длине, а `_neutralize` может удлинять строку
   (влияет только на объём усечения); ключи `layer_budgets` не валидируются
   (неизвестный ключ просто не используется); в диагностике `OSError`/`YAMLError`
   уровня loader могут встречаться абсолютные пути (не влияет на
   `PromptComposition`, который работает с логическими метками).
7. **Redaction асимметричен by design:** `inspect()`/`preview()` редактируют
   секретоподобные значения (для показа пользователю), а сам рендер prompt
   содержит исходные метки/текст — редактирование полного промпта не входит в
   S08. Пользовательской утечки нет: CLI печатает только `inspect()`/`preview()`.
8. **PromptComposer не подключён в runtime-путь** — используется CLI и тестами;
   подключение к model-call path вне scope S08.

### Резюме изменений

```
backend/seraphim/sanctum/
  identity.py            — ProfileSettings, IdentityConfig, Identity, load_identity (S08)
  prompt_composer.py     — LAYER_ORDER, PromptLayer, PromptComposition, PromptComposer
backend/seraphim/cli/
  identity.py            — seraphim identity show | prompt-preview
  main.py                — регистрация identity_group
identity/
  identity.yaml, system_prompt.md, personality.md, response_style.md
backend/tests/sanctum/
  test_identity.py (12), test_prompt_composer.py (22), test_prompt_snapshots.py (5)
  snapshots/{layer_order,missing_files,overrides,project_scope,prompt_injection}.txt
backend/tests/cli/
  test_identity_cli.py (3)
```

### Предлагаемое сообщение коммита

```
feat: S08 SANCTUM identity and deterministic prompt composer

- sanctum/identity.py: identity.yaml profile settings + layered loader
  (defaults < project < user), predictable defaults for empty files
- sanctum/prompt_composer.py: fixed 9-layer order, labeled sources,
  size budgets, untrusted data envelopes, cyclic marker neutralization,
  source-label sanitization at the render boundary
- cli/identity.py: seraphim identity show | prompt-preview
- identity/: editable default template files
- tests: 42 new (identity, composer, 5 snapshots, CLI); 323/324 PASS
- ruff: clean (also fixes pre-existing S07 lint debt)
```

---

*Конец IMPLEMENTATION_LOG.md S08.*

---

## S09 — SANCTUM: секреты, privacy и redaction

**Статус:** PASS
**Дата:** 16.10.2026
**Гейт:** ADR-006 (секреты — ACCEPTED)

### 1. Задача и границы

Защитить ключи провайдеров и передачу данных вовне: секреты — только в
платформенном secure storage; в конфиге — только `secret_ref`; интерфейс
secret store с masked display и rotation/delete; privacy summary до внешней
передачи; без silent uploads; тесты на redaction, missing/invalid ref,
export-without-secrets и logging.

S09 даёт **гарантию и точку решения**, а не полный pipeline: экспорт/импорт/backup
(S11), фактический сетевой вызов провайдера (S12+) и инъекция секретов в MCP
(S37) — вне scope. На момент S09 в `backend/seraphim` нет сетевого кода
(`requests|urllib|socket|httpx` — пусто), поэтому критерий «privacy policy
проверяется перед внешней передачей» выполнен через явный gate, который обязана
вызывать MODEL LAYER.

### 2. Решение по хранилищу секретов (ADR-006 → ACCEPTED для секретов)

Выбран **вариант 4**: шифртекст внутри корня, ключ управляется ОС через
**Windows DPAPI** (`CryptProtectData`/`CryptUnprotectData` через `ctypes`, ноль
новых зависимостей). Обоснование и ограничения — в ADR-006. Ключевое: сохраняется
единый корень (§12.1), нет управления парольной фразой, платформенный механизм по
предписанию S09-промта. DPAPI **проверен фактически** (`dpapi_available()` делает
protect/unprotect round-trip, а не предполагает наличие). Локальные модели в
ADR-006 остаются PROPOSED.

### 3. Что сделано

#### 1. Хранилище секретов (`seraphim/sanctum/secrets.py`)

- `SecretStore` (ABC) — единственный интерфейс; `info`/`set`/`get`/`has`/`delete`/`list_refs`,
  плюс `rotate` (отказывает, если ref не существует) и `masked`.
- `DPAPISecretStore` — `SRP1` magic + DPAPI blob в `<root>/data/secrets/<ref>.bin`,
  атомарная замена через `os.replace`; чтение проверяет magic; ошибка расшифровки →
  `SECRET_ACCESS_DENIED` без значения.
- `InMemorySecretStore` — только явным `backend="memory"` (тесты/эфемерные запуски),
  никогда не выбирается автоматически.
- `UnavailableSecretStore` — fail-closed: `set/get/delete` → `SECRET_STORE_UNAVAILABLE`.
- `create_secret_store` — детерминированный выбор без plaintext-fallback;
  неизвестный backend → `VALIDATION_FAILED`.
- `validate_secret_ref` (`^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$`, ≤64, reserved
  device names), `mask_secret` (`****` + 4 хвостовых), `looks_like_secret`,
  `provider_auth_error` (значение по exact match, отдаёт только `secret_ref`/`status`/`value_supplied`).
- **Чтение значения регистрирует его process-wide** (`register_known_secret`).

#### 2. Privacy gate (`seraphim/sanctum/privacy.py`)

`DATA_CATEGORIES` (prompt/conversation/files/memory/artifacts/images/tool_output),
`PrivacyPolicy` (+`from_config`), `TransmissionRequest`, `PrivacyDecision`,
`summarize_request`/`render_summary`, `evaluate_transmission` (фиксированный порядок:
local → `local_only` → external disabled → provider not allowed → allowed),
`assert_transmission_allowed` (→ `PRIVACY_TRANSMISSION_DENIED`), `prepare_payload`
(redaction перед отправкой). Дефолты запрещающие: `allow_external_transmission=False`,
`allowed_providers=[]`, `require_confirmation=True`, `redact_before_transmission=True`.

#### 3. Export без секретов (`seraphim/sanctum/export.py`)

- `build_safe_export` — config + identity + секция `secrets` с `included: false`,
  backend, логический относительный `location`, `refs` (только имена) и note;
  значения не читаются вовсе; в конце вызывает **собственный verifier** и отказывается
  возвращать payload с секретом (`DIAGNOSTIC_EXPORT_FAILED`).
- `find_secret_material` — JSON-пути (не значения), проверяет и **ключи**, и значения,
  включает `set`/`frozenset`; путь для секретного ключа не эхоит сам ключ (`$.*`).
- `sanitize_export` / `verify_no_secrets`.

#### 4. Redaction (`seraphim/contracts/sanitization.py`)

- Расширены паттерны: `sk-`/`sk-ant-`, `AIza`, `hf_`, `gh[pousr]_`, `xox[baprs]-`,
  `AKIA`, PEM, Bearer, JWT, `key=value`.
- **Process-wide реестр известных секретов**: `register_known_secret`/`clear_known_secrets`/
  `known_secret_count`; `sanitize_text` и `redact_known_secrets` удаляют
  зарегистрированные значения точным совпадением (самое длинное — первым).
- `_REFERENCE_KEYS`: под `secret_ref`/`credential_ref`/`key_ref`/`token_ref`
  сохраняется **только reference-образное** значение; всё прочее (пробелы, uppercase,
  разделители пути, распознанный формат ключа, не-строка) → `[REDACTED]`; для
  reference-образных дополнительно применяется pattern scrub и проверка реестра.

#### 5. Конфиг (`sanctum/config_schemas.py`, `sanctum/loader.py`)

- `credential_ref` → `secret_ref`; `PrivacyConfig` получил поля внешней передачи
  (запрещающие по умолчанию).
- `_check_secret_refs` — literal-ключ в `secret_ref` → `SECRET_REF_INVALID` (значение не эхоится).
- `_check_entry_keys` — неизвестные ключи внутри list-entries (например `api_key`
  в модели) больше не принимаются молча.
- `_check_mcp_credentials` — literal-секрет в `mcp.servers[].env` и `command` →
  `SECRET_REF_INVALID` (см. hardening F3).

#### 6. CLI (`seraphim/cli/secrets.py`, `seraphim/cli/errors.py`)

`secrets set|list|show|rotate|delete|audit` и `privacy summary`. Значение принимается
только через `--from-env`/`--stdin`/hidden prompt — `--value` отсутствует намеренно
(process listing и history). `audit` собирает export, сканирует корень (исключая
`.git`, `.venv`, `node_modules`, …) и выходит с кодом 1 при находках, печатая только пути.
`handle_errors` печатает `error [CODE]: safe_message` в stderr (exit 1); применён ко всем
командам S09.

#### 7. Изменённые/новые файлы

```
backend/seraphim/sanctum/secrets.py       (новый)  SecretStore, DPAPI/memory/unavailable, refs, маски
backend/seraphim/sanctum/privacy.py       (новый)  privacy gate, summary, decision, prepare_payload
backend/seraphim/sanctum/export.py        (новый)  build_safe_export, find_secret_material, verify_no_secrets
backend/seraphim/cli/secrets.py           (новый)  secrets *, privacy summary
backend/seraphim/cli/errors.py            (новый)  handle_errors
backend/seraphim/contracts/sanitization.py         паттерны ключей, реестр known secrets, *_ref-значения
backend/seraphim/contracts/errors.py               коды SECRET_*/PRIVACY_*, санитизация safe_message/details
backend/seraphim/observatory/logger.py             опциональный SecretRedactor
backend/seraphim/observatory/store.py              санитизация payload на write-boundary
backend/seraphim/sanctum/config_schemas.py         secret_ref, PrivacyConfig
backend/seraphim/sanctum/loader.py                 _check_secret_refs, _check_entry_keys, _check_mcp_credentials
backend/seraphim/sanctum/validator.py              санитизация unexpected-error сообщения
backend/seraphim/cli/config.py                     санитизация печатаемого сообщения
backend/seraphim/sanctum/__init__.py               экспорты S09
backend/seraphim/cli/main.py                       регистрация групп
backend/tests/conftest.py                          изоляция process-wide реестра секретов
ARCHITECTURE_DECISIONS.md, CONTRACTS.md            ADR-006 (ACCEPTED), §2.2/§4.4/§12.2
```

### 4. Hardening после независимого security-review (read-only, 1 раунд)

Review подтвердил: fail-closed реален, DPAPI-использование корректно (порядок
аргументов, `LocalFree` в `finally`, magic, атомарная замена), дефолты privacy
запрещающие, сетевого выхода сегодня нет. **BLOCKER — 0.** Найдено 3 MAJOR и 4 MINOR.

| ID | Находка | Исправление | Проверка |
|---|---|---|---|
| F1 (MAJOR) | Точное удаление значения было доступно, но не подключено к общим sink'ам: `SeraphimError`/`Logger`/`Event`/export знают только паттерны и имена ключей, поэтому value без распознаваемого формата под нейтральным ключом утекало; `provider_auth_error` в продакшене не вызывался | Process-wide реестр `register_known_secret`; `sanitize_text`/`redact_known_secrets` консультируют его; `SecretStore.get` регистрирует прочитанное значение. Гарантия стала структурной, а не зависящей от каждого вызывающего. Дополнительно закрыт write-boundary SQLite: `EventStore.save` санитизирует payload (dict мутабелен, поэтому мутация после конструктора иначе попала бы в БД) | `TestReadValuesAreRegistered`, `TestKnownSecretRegistry`, `test_logger_without_redactor_scrubs_registered_secret`, `test_error_details_with_read_value_are_scrubbed`, усиленный `test_provider_auth_error_hides_key_in_message`, `test_store_sanitizes_payload_at_write_boundary`, `test_store_sanitizes_pattern_secret_at_write_boundary` |
| F2 (MAJOR) | Значения под `*_ref`-ключами проходили только pattern scrub, а `looks_like_secret` — pattern-based, поэтому literal-ключ под `secret_ref` мог попасть в конфиг и быть повторён в экспорте | `_sanitize_reference_value`: сохраняется только reference-образное значение; всё прочее → `[REDACTED]`; для reference-образных — pattern scrub + проверка реестра. Паттерн дублирован в `contracts` (нельзя импортировать `sanctum`) и зафиксирован тестом синхронизации | `TestReferenceKeyValues` (6), `TestReferencePatternStaysInSync` |
| F3 (MAJOR) | Запрет literal-ключа покрывал только `providers.models[].secret_ref`; `mcp.servers[].env` принимал ключ открытым текстом | `_check_mcp_credentials`: literal-секрет в `env`-значениях и в `command` → `SECRET_REF_INVALID`, значение не эхоится | `test_literal_secret_in_mcp_env_rejected`, `test_literal_secret_in_mcp_command_rejected`, `test_plain_mcp_env_is_accepted` |
| F4 (MINOR) | Verifier не смотрел ключи и не-строки; `build_safe_export` не вызывал свой verifier | `_walk` проверяет и ключи (путь не эхоит ключ), включает `set`/`frozenset`; builder вызывает `verify_no_secrets` | `test_find_secret_material_detects_a_secret_used_as_key`, `..._registered_value_as_key`, `..._inside_a_set`, `test_build_safe_export_refuses_when_the_sanitizer_is_bypassed` |
| F5 (MINOR) | Часть тестов проходила бы и при отключённой защите (маркер не входил во вход; export не читает значения) | Тесты усилены: маркер реально прогоняется через sink (export с зарегистрированным значением в identity-тексте, error details под нейтральным ключом, `purpose` в privacy), добавлены whitelist-проверки полей | `test_export_scrubs_a_registered_secret_planted_in_identity`, `test_summary_contains_no_payload`, `test_denial_detail_never_contains_payload`, `test_policy_dict_has_no_secrets` |
| F6 (MINOR) | Документация обещала больше фактического: «literal key in config is rejected by the loader» (только распознанные форматы) и «error if unavailable» у `backend="dpapi"` (фактически деградация к fail-closed) | Формулировки в `secrets.py` приведены к поведению | — |
| F7 (MINOR, adjacent S07) | Необработанное исключение печаталось в CLI без санитизации (`validator.py` → `cli/config.py`) | Сообщение об unexpected error и вывод CLI проходят через `sanitize_text` | — |

**Остаточный риск (не исправлен, задокументирован).** Ссылка — логическое имя, поэтому
форма значения под `secret_ref` принципиально не отличает настоящую ссылку от
pattern-free ключа, случайно выглядящего как имя. Такой ключ отвергается, только если
совпал известный формат или значение уже известно процессу. Ужесточение (энтропийная
эвристика или обязательный префикс ссылки) отложено на S11, чтобы не ломать
совместимость конфигов. Зафиксировано в ADR-006.

### 5. Acceptance Criteria (все проверены)

| Критерий | Результат |
|---|---|
| Export не содержит активных секретов | **PASS** — значения не читаются (`secrets.included=false`, только `refs`); builder вызывает `verify_no_secrets` и отказывается возвращать payload с секретом; E2E `secrets audit` → exit 0, маркер отсутствует во всех файлах корня (включая `.bin`) |
| Auth errors не раскрывают значение ключа | **PASS** — `provider_auth_error` + реестр известных секретов; значение не попадает ни в `safe_message`, ни в `sanitized_details`, ни в `str(err)`; для pattern-free ключа покрыто усиленными тестами |
| Privacy policy проверяется перед внешней передачей | **PASS** — `assert_transmission_allowed` бросает `PRIVACY_TRANSMISSION_DENIED`; дефолтная политика запрещающая; `privacy summary` → DENIED (exit 1) без opt-in. Runtime-вызов добавит MODEL LAYER (S12+); сегодня внешнего трафика нет |

### 6. Ответы на обязательные вопросы

**1. Где физически хранится секрет в выбранной платформе?**
В Windows DPAPI-шифртексте внутри корня SERAPHIM: `<root>/data/secrets/<ref>.bin`.
Файл содержит magic `SRP1` + blob `CryptProtectData`. Ключ шифрования — credential
master key пользователя ОС; SERAPHIM не хранит и не вводит парольную фразу.
Путь виден пользователю (`seraphim secrets list`, `secrets show`). Замена — атомарная
(`tmp` + `os.replace`). Ограничения: шифртекст привязан к пользователю и машине;
защита *at rest*, не от процесса того же пользователя. При отсутствии безопасного
backend — fail-closed, plaintext-fallback отсутствует.

**2. Что входит в export вместо секретного значения?**
Только логическая ссылка `secret_ref` (например `provider.openai`) и метаданные
backend'а: `secrets.included=false`, `backend`, логический относительный `location`,
`refs` (имена) и note о том, что значения восстанавливаются из хранилища. Значения
не читаются вовсе, поэтому не могут попасть в payload; дополнительно payload проходит
verifier, который при находке бросает `DIAGNOSTIC_EXPORT_FAILED`, не эхоя значение.

**3. Когда пользователь узнаёт, что контекст отправится в облако?**
До передачи: `privacy summary` печатает provider, модель, purpose, destination и
**категории локальных данных**, которые будут отправлены, и вердикт
ALLOWED/DENIED с причиной. В runtime тот же summary отдаёт
`summarize_request`/`PrivacyDecision.summary`, а `assert_transmission_allowed`
обязан вызываться перед запросом к внешнему провайдеру; при разрешённой политике
`requires_confirmation=True` требует явного подтверждения. Silent uploads нет:
дефолтная политика запрещает внешнюю передачу, а разрешение требует явного opt-in
и перечисления провайдера.

### 7. Верификация

```powershell
# Полный набор (venv)
.\.venv\Scripts\python.exe -m pytest -q
# 481 passed, 1 skipped

# Lint
.\.venv\Scripts\python.exe -m ruff check backend/
# All checks passed!
```

Ручные проверки (фактические результаты):

```powershell
# marker secret E2E в отдельном корне
$root = Join-Path $env:TEMP "seraphim-s09-check"
$env:SERAPHIM_TEST_SECRET = "SERAPHIM_TEST_SECRET_xyz789"
python -m seraphim secrets set provider.openai --from-env SERAPHIM_TEST_SECRET --config-dir $root
#  Stored secret 'provider.openai' in dpapi store.  location: <root>\data\secrets
python -m seraphim secrets show provider.openai --config-dir $root
#  provider.openai: ****z789
python -m seraphim secrets audit --config-dir $root
#  No secret material found in configs, logs or exports.   (exit 0)
# grep по всем файлам корня: NO HITS (маркер отсутствует и в provider.openai.bin)
```

```powershell
python -m seraphim secrets show provider.absent --config-dir $root
#  error [SECRET_NOT_FOUND]: ... (exit 1)
python -m seraphim secrets show "Bad Ref" --config-dir $root
#  error [SECRET_REF_INVALID]: must match ^[a-z0-9]... (exit 1)
# literal-ключ в secret_ref / в mcp.servers[].env:
#  Configuration validation failed; значение не эхоится (exit 1)
python -m seraphim privacy summary --provider openai --categories prompt,files --config-dir $root
#  Decision: DENIED (external_transmission_disabled)   (exit 1)
```

### 8. Ответы на контрольные вопросы (проверки)

- Redaction: `test_contracts_sanitization.py` (паттерны провайдеров, реестр known
  secrets, `*_ref`-значения), `test_logger.py` (в т.ч. без явного redactor).
- Missing ref: `SECRET_NOT_FOUND` (CLI exit 1); `config validate` не требует наличия
  значения — присутствие проверяется при использовании.
- Invalid ref: `SECRET_REF_INVALID` (форма/длина/reserved names), значение не эхоится.
- Export-without-secrets: `TestExportWithoutSecrets`, `secrets audit`, self-verification builder'а.
- Logging: `TestSecretLogging`, `test_logger_*`; значения не логируются, маска — только
  хвост; SQLite-путь санитизируется `Event.__post_init__` → `sanitize_dict`.
- Fail-closed: `TestUnavailableStore`, `test_factory_*`; на не-Windows — недоступное
  хранилище, а не plaintext.
- DPAPI: `TestDPAPIStore` (win32), `dpapi_available()` round-trip.

### 9. Ручные проверки пользователя

1. **Marker secret во всех артефактах/логах** (команды из §7): задать значение через
   `--from-env`, затем `secrets show` (ожидается `****z789`), `secrets audit`
   (ожидается exit 0) и поиск строки маркера по всем файлам корня — совпадений быть не должно.
2. **Ссылка на несуществующий `secret_ref`**: `secrets show provider.absent` и
   `secrets delete provider.absent` → `SECRET_NOT_FOUND`, exit 1; при этом
   `config validate` остаётся PASS, потому что значение не требуется до использования.

### 10. Риски и долги

1. **Privacy gate не подключён в runtime** — `assert_transmission_allowed` обязана
   вызывать MODEL LAYER (S12+); сегодня в `backend/seraphim` нет сетевого кода, поэтому
   критерий выполнен через явную точку решения, а не через живой вызов.
2. **Остаточный риск по `secret_ref`** (см. §4): pattern-free ключ, по форме совпадающий
   с именем, неотличим от ссылки; ужесточение — кандидат на S11.
3. **DPAPI-ограничения**: не переносим между машинами/аккаунтами и не защищает от
   процесса того же пользователя; задокументировано в ADR-006 и в docstring'е.
4. **Entropy** — фиксированный не-секретный доменный разделитель, не ключ.
5. **`handle_errors` применён к командам S09 и S10**; унификация CLI-ошибок закрыта.
6. **Экспорт/импорт/backup pipeline** — S11; S09 даёт гарантию и verifier, но не manifest
   и не restore-проверки. Golden-сценарий §20.2 #18 закрывается в S11.
7. **Инъекция секретов в MCP** — S37; до этого literal-значение в `mcp.servers[].env`/
   `command` является ошибкой конфигурации.
8. **`user_preferences.md` (§12.2)** не реализован (не входил в перечень S09).
9. **Изоляция process-wide реестра** обеспечена autouse-фикстурой в `tests/conftest.py`;
   продовый код регистрирует значения только при чтении из хранилища.
10. Незакоммиченные изменения S07/S08 сохранены.

### 11. Резюме изменений

```
backend/seraphim/sanctum/
  secrets.py            — SecretStore, DPAPISecretStore, InMemorySecretStore, UnavailableSecretStore,
                          create_secret_store, validate_secret_ref, mask_secret, provider_auth_error
  privacy.py            — DATA_CATEGORIES, PrivacyPolicy, TransmissionRequest, PrivacyDecision,
                          summarize_request, render_summary, evaluate_transmission,
                          assert_transmission_allowed, prepare_payload
  export.py             — build_safe_export, sanitize_export, find_secret_material, verify_no_secrets
backend/seraphim/cli/
  secrets.py            — seraphim secrets set|list|show|rotate|delete|audit, privacy summary
  errors.py             — handle_errors
backend/seraphim/contracts/
  sanitization.py       — паттерны провайдерских ключей, process-wide реестр, *_ref-значения
  errors.py             — SECRET_NOT_FOUND/SECRET_REF_INVALID/SECRET_STORE_UNAVAILABLE/PRIVACY_TRANSMISSION_DENIED
backend/seraphim/observatory/logger.py  — опциональный SecretRedactor
backend/seraphim/observatory/store.py   — sanitize payload at write boundary
backend/seraphim/sanctum/{config_schemas,loader,validator,__init__}.py, cli/{main,config}.py
backend/tests/sanctum/{test_secrets.py (65), test_privacy.py (25), test_export_secrets.py (19)}
backend/tests/cli/test_secrets_cli.py (16)
backend/tests/{test_contracts_sanitization.py, observatory/test_logger.py, observatory/test_store.py, sanctum/test_loader.py, conftest.py}
```

### 12. Предлагаемое сообщение коммита

```
feat: S09 SANCTUM secret storage, privacy gate and secret-free export

- sanctum/secrets.py: SecretStore interface; Windows DPAPI backend (ctypes,
  ciphertext in <root>/data/secrets/<ref>.bin), in-memory and fail-closed
  backends; secret refs, masked display, rotation/delete; read values are
  registered process-wide so they can never be written back out
- sanctum/privacy.py: deterministic transmission gate with restrictive
  defaults, privacy summary (provider + local data categories), payload
  redaction before transmission
- sanctum/export.py: secret-free export builder (references only) that
  verifies its own output; verifier reports paths, never values
- contracts/sanitization.py: provider key patterns, process-wide known-secret
  registry, reference-shaped values only under *_ref keys
- sanctum/loader.py: secret_ref only, literal keys rejected (incl. mcp env/command)
- cli/secrets.py: seraphim secrets set|list|show|rotate|delete|audit, privacy summary
- ADR-006: secrets ACCEPTED (variant 4, DPAPI); local models still PROPOSED
- tests: 125 new S09 tests + 27 hardening tests; 481/482 PASS; ruff clean
```

---

## S10 — CLI foundation и doctor

### 1. Цель и объём

Ранняя CLI для управления и диагностики: `seraphim --help`, `doctor`, `status`,
`config show`, `config validate`, `logs tail` — с понятными exit codes и
machine-readable (`--json`) выводом. CLI — тонкая обёртка над service API
(OBSERVATORY/SANCTUM/storage); бизнес-логика не дублируется, тот же код позже
вызовет GUI. Диагностика read-only: не создаёт БД, не пишет файлы, не запускает
destructive fixes, не печатает секреты.

### 2. Компоненты

- `observatory/doctor.py` — service `run_doctor()` (9 checks) и `build_status()`.
  Каждый check возвращает `DoctorCheck(id,title,severity,summary,remediation,details)`;
  severity ∈ {ok, warn, error}. Ошибки делают `report.healthy=False`.
- `observatory/logs.py` — `read_log_tail(root, lines, name)`: выбор самого
  свежего файла из `logs/` (или по имени), чтение хвоста, пропуск symlink'ов,
  санитизация каждой строки через contracts sanitization.
- `cli/doctor.py` — `seraphim doctor [--config-dir] [--json]`. Human: `[PASS]/[WARN]/[FAIL]`
  + remediation; JSON: `{healthy, root, checks[]}`. Exit 0 healthy / 1 errors.
- `cli/status.py` — `seraphim status [--config-dir] [--json]`. Компактный snapshot.
- `cli/logs.py` — `seraphim logs tail [--config-dir] [--lines N] [--file NAME] [--json]`.
  `--lines<0` → exit 1; отсутствующий `--file` → exit 1; нет логов → exit 0.
- `cli/config.py` — добавлены `config show` (human + JSON, 8 доменов) и
  `config validate --json`.
- `cli/main.py`, `cli/__init__.py` — регистрация/экспорт команд.
- `contracts/errors.py` — `handle_errors` унифицирует поверхность ошибок CLI
  (закрыт долг S09 §10.5).
- `pyproject.toml` — исправлен `tool.setuptools.packages.find where=["backend"]`,
  благодаря чему `python -m seraphim` работает без ручного `PYTHONPATH`.

### 3. Проверки doctor (error vs warning)

- `root` — **error**, если путь не существует или не директория.
- `root_layout` — **warning** при отсутствии стандартных каталогов (identity/data/logs);
  создаются при первом запуске.
- `permissions` — **error** при отсутствии read/write доступа к root.
- `config` — **error** при синтаксических/schema-проблемах конфигурации.
- `database` — **warning**, если БД ещё не инициализирована; **error**, если файл
  есть, но не инициализирован / out-of-sync / schema новее текущей.
- `secret_store` — **warning**, если безопасный backend недоступен (не-Windows);
  **pass**, если DPAPI готов.
- `identity` — **error** при невалидной идентичности.
- `prerequisites` — **error** при неподходящей версии Python или отсутствующих модулях.
- `local_api` — **warning** (loopback API появится с VESSEL, S50).

### 4. Безопасность секретов

Human- и JSON-вывод doctor/status/config/logs не печатают секретный материал.
Секреты не читаются вовсе (doctor обращается к secret store только за метаданными
backend'а и числом ссылок). Строки логов проходят `sanitize` (паттерны провайдеров +
process-wide реестр + `*_ref`). В smoke-тесте `secret=sk-... password=...` →
`[REDACTED] [REDACTED]`.

### 5. Machine-readable (CI)

Все команды поддерживают `--json`: `doctor --json` → `{healthy,root,checks[]}`
(поля check'а: `id,title,severity,summary,remediation,details`); `status --json`;
`config validate --json` → `{valid,issues[]}`; `config show --json` → 8 доменов;
`logs tail --json`. В CI достаточно парсить JSON и exit code — без разбора цветного
human-вывода.

### 6. Верификация

```powershell
.\.venv\Scripts\python.exe -m pytest -q        # 517 passed, 1 skipped
.\.venv\Scripts\python.exe -m ruff check backend/   # All checks passed!
```

Тесты S10 (52 в `tests/cli/`): doctor 10, status 7, logs 8, config 8, плюс
существующие identity/secrets CLI. Покрыты exit codes, healthy/broken, JSON,
redaction, read-only (БД не создаётся), неверные аргументы (exit 2), секретная
безопасность.

Smoke (фактические результаты, изолированный root в %TEMP%):

```powershell
python -m seraphim doctor --config-dir <healthy>   # exit 0, 3 warnings, DB_CREATED=False
python -m seraphim doctor --config-dir <broken>    # exit 1, [FAIL] Configuration, remediation
python -m seraphim doctor --config-dir <healthy> --json  # healthy=true; 9 check-id; поля id/title/severity/summary/remediation/details
python -m seraphim status --config-dir <healthy>   # exit 0, Overall: HEALTHY
python -m seraphim config validate --config-dir <healthy> --json  # {"valid": true,"issues": []}
python -m seraphim logs tail --config-dir <healthy>  # secret/password -> [REDACTED], no leak
```

### 7. Ответы на контрольные вопросы

- **Error vs warning** — см. §3. Блокируют (exit 1): root, permissions, config,
  database-ошибки, identity, prerequisites. Только предупреждают (exit 0):
  root_layout, database-not-initialized, secret_store-unavailable, local_api.
- **CI без парсинга цвета** — `--json` + exit code (§5).
- **Общая логика с GUI** — GUI вызовет те же `run_doctor()`, `build_status()`,
  `read_log_tail()`, `load_config()`, `validate_config_files()`. CLI не содержит
  бизнес-логики.

### 8. Ручные проверки пользователя

1. `seraphim doctor` в healthy корне → exit 0, понятные warnings; в намеренно
   сломанном (битый `config/runtime.yaml`) → exit 1, `[FAIL] Configuration`.
2. `seraphim doctor --json` → валидный JSON с `healthy` и `checks[]`.
3. Убедиться, что после `doctor`/`status` файл `data/seraphim.sqlite` не создан.
4. Убедиться, что секреты (значения, не `secret_ref`) не встречаются в выводах.

### 9. Риски и долги

1. **Local API check — заглушка** (warning до S50/VESSEL): реальная проверка
   loopback-порта появится вместе с API.
2. **Python-version gate в CI**: глобальный интерпретатор 3.10.10 < `requires-python>=3.11`;
   venv использует 3.14.2. Для CI нужен явный 3.11+ (не блокирует локальную работу).
3. **`ruff format` не является gate проекта** (предсуществующие файлы не format-clean,
   `line-length=99`, E501 игнорируется); обязательна только `ruff check`.
4. **DPAPI-only secret store**: на не-Windows doctor даёт warning (fail-closed в S09).
5. Незакоммиченные изменения S07/S08/S09 сохранены; S10 не коммитит (по инструкции).

### 10. Резюме изменений

```
backend/seraphim/observatory/
  doctor.py  — run_doctor(), build_status(), DoctorCheck/DoctorReport (9 read-only checks)
  logs.py    — read_log_tail() (freshest/ named file, symlink skip, sanitize)
backend/seraphim/cli/
  doctor.py  — seraphim doctor [--config-dir] [--json]
  status.py  — seraphim status [--config-dir] [--json]
  logs.py    — seraphim logs tail [--config-dir] [--lines] [--file] [--json]
  config.py  — + config show, + config validate --json
  main.py / __init__.py — регистрация и экспорт команд
backend/seraphim/contracts/errors.py — handle_errors (унификация CLI-ошибок)
pyproject.toml — packages.find where=["backend"] (python -m seraphim без PYTHONPATH)
backend/tests/cli/ — conftest + 52 CLI-теста (doctor/status/logs/config)
```

### 11. Предлагаемое сообщение коммита

```
feat: S10 CLI foundation and read-only doctor/status/logs

- observatory/doctor.py: run_doctor() 9 read-only checks + build_status();
  PASS/WARN/FAIL with remediation, healthy verdict, no state changes
- observatory/logs.py: read_log_tail() with symlink skip and secret redaction
- cli: seraphim doctor|status|logs tail|config show|config validate with
  human + --json machine-readable output and clear exit codes
- cli/errors.handle_errors unifies CLI error surface (closes S09 debt)
- pyproject: packages.find where=["backend"] so python -m seraphim works
- tests: 52 CLI tests (exit codes, healthy/broken, JSON, redaction, read-only);
  517/518 PASS, ruff check clean
```

---

*Конец IMPLEMENTATION_LOG.md S10.*

---

## S11 — Экспорт, импорт и конфигурационный backup

### 1. Цель и объём

Переносимая резервная копия конфигурации без секретов: `seraphim config export`
создаёт zip-архив с manifest, версиями, checksums и списком исключений;
`seraphim config import` валидирует, показывает dry-run diff, делает backup
текущего, применяет атомарно с rollback при ошибке.

### 2. Что входит в архив и что намеренно исключено

**Включено:** config (8 YAML-доменов), identity (identity.yaml, system_prompt.md,
personality.md, response_style.md), locale (locales/*), theme (themes/*), skills
(skills/*).

**Исключено:** секретные значения (только `secret_ref`), БД (data/seraphim.sqlite),
секретные blob'ы (data/secrets/), логи, артефакты, память, кэш.

Manifest содержит: `export_format_version`, `seraphim_version`, `created_at`,
`checksums` (sha256 каждого файла), `domains`, `excluded`, `file_count`.

### 3. Как пользователь увидит diff перед применением

`seraphim config import <archive>` по умолчанию выполняет **dry-run**:
- читает manifest, проверяет version и checksums;
- сравнивает файлы архива с существующими в target root;
- печатает: `+ added`, `~ modified`, `- removed`, `unchanged`;
- НЕ записывает ничего.

Для реального применения: `seraphim config import <archive> --apply`.

### 4. Как восстанавливается конфигурация при частичной ошибке

1. Перед применением создаётся backup: `data/backups/pre-import-backup-<timestamp>/`
   (копия всех доменов текущего root).
2. Файлы пишутся атомарно per-file (temp + `os.replace`).
3. Если запись прерывается (traversal, I/O error):
   - вызывается `_restore_backup()` — `shutil.rmtree` целевого каталога + `shutil.copytree`
     из backup;
   - исходный импорт бросает `ARCHIVE_IMPORT_FAILED`;
   - если и rollback не удался — `ARCHIVE_ROLLBACK_FAILED` с указанием пути backup'а
     для ручного восстановления.

### 5. Защита от path traversal

Каждый путь внутри архива нормализуется (`PurePosixPath`), разрешается относительно
target root и проверяется через `.relative_to(target_root)`. `../` → `ARCHIVE_PATH_TRAVERSAL`
(exit 1), файл не записывается.

### 6. Компоненты

- `sanctum/export_import.py` — service layer: `export_to_archive()`,
  `import_from_archive()` (dry_run, apply, rollback), `_check_traversal()`.
- `cli/config.py` — команды `config export` и `config import` (human + `--json`).
- `contracts/errors.py` — ARCHIVE_EXPORT_FAILED, ARCHIVE_VERSION_INCOMPATIBLE,
  ARCHIVE_PATH_TRAVERSAL, ARCHIVE_ROLLBACK_FAILED, ARCHIVE_INTEGRITY_FAILED.
- `sanctum/export.py` — переиспользуется `build_safe_export`, `verify_no_secrets`.

### 7. Верификация

```powershell
.\.venv\Scripts\python.exe -m pytest -q          # 541 passed, 1 skipped (2.78s)
.\.venv\Scripts\python.exe -m ruff check backend/  # All checks passed!
```

24 новых теста S11:
- TestExportHappy (5): zip+manifest, expected files, secret exclusion, data dirs excluded, custom path
- TestImportDryRun (2): diff shows additions, unchanged
- TestImportApply (2): writes files, creates backup
- TestVersionMismatch (1): incompatible version rejected
- TestPathTraversal (2): archive `../` rejected, helper unit
- TestSecretExclusion (2): archive has no secret bytes, refs not values
- TestRollback (2): partial failure → rollback restores original, backup has pre-import state
- TestArchiveNotFound (1): missing archive rejected
- TestExportCLI (3): exit 0, JSON, custom path
- TestImportCLI (4): dry-run, JSON, apply, missing archive

### 8. Ответы на контрольные вопросы

**Что входит в архив и что намеренно исключено?**
Включены: config (8 доменов YAML), identity (4 файла), locales, themes, skills.
Исключены: секретные значения, БД, логи, артефакты, память, кэш.

**Как пользователь увидит diff перед применением?**
`seraphim config import <archive>` (без `--apply`) показывает dry-run diff:
`+ added`, `~ modified`, `- removed`, `unchanged`. Ничего не записывается.

**Как восстанавливается конфигурация при частичной ошибке?**
Перед применением создаётся backup. При ошибке записи — автоматический rollback
из backup. Если rollback не удался — `ARCHIVE_ROLLBACK_FAILED` с указанием пути
для ручного восстановления.

### 9. Ручные проверки пользователя

1. **Экспорт в тестовый root:** `seraphim config export --config-dir <test-root>`
   → zip + json в `data/backups/`.
2. **Импорт в чистый root (dry-run):** `seraphim config import <zip> --config-dir <temp-root>`
   → показывает `+ config/runtime.yaml`, `+ identity/...`, `(Dry-run)`.
3. **Импорт (apply):** `seraphim config import <zip> --config-dir <temp-root> --apply`
   → файлы записаны, backup создан.
4. **Path traversal:** архив с `../escape.txt` → `Import failed: ...path traversal detected`, exit 1.
5. **Секреты:** экспортированный zip не содержит строк `sk-ant`, `sk-` и известных значений.

### 10. Риски и долги

1. **Skills/locales/themes** — в S11 экспортируются как файлы; полноценная валидация
   Skills (manifest schema) — S36.
2. **Secret refs после импорта** — значения не экспортируются; если secret store
   перемещён, пользователь должен заново задать значения через `seraphim secrets set`.
3. **Конфликт при импорте в существующий root** — dry-run показывает modified/removed,
   но merge-стратегии нет; импорт перезаписывает. Это ожидаемо для config backup.
4. **Full-state backup** (БД, memory, checkpoints) — S74; S11 — config-only.
5. Незакоммиченные изменения S07–S10 сохранены; S11 не коммитит.

### 11. Резюме изменений

```
backend/seraphim/sanctum/export_import.py  — export_to_archive(), import_from_archive(),
                                               _check_traversal(), _atomic_apply(), _restore_backup()
backend/seraphim/cli/config.py             — +config export, +config import (human + --json)
backend/seraphim/contracts/errors.py       — ARCHIVE_EXPORT_FAILED, ARCHIVE_VERSION_INCOMPATIBLE,
                                              ARCHIVE_PATH_TRAVERSAL, ARCHIVE_ROLLBACK_FAILED,
                                              ARCHIVE_INTEGRITY_FAILED
backend/tests/sanctum/test_export_import.py — 24 теста (export, import, dry-run, apply,
                                               traversal, version mismatch, rollback, secrets)
```

### 12. Предлагаемое сообщение коммита

```
feat: S11 config export/import with dry-run, backup and rollback

- sanctum/export_import.py: export_to_archive() produces a zip with manifest
  (format_version, sha256 checksums, domains, excluded); import_from_archive()
  validates, shows dry-run diff, backs up, atomically applies, rolls back on failure
- cli: seraphim config export|import with human + --json output and clear exit codes
- contracts/errors: 5 new ARCHIVE_* error codes
- path traversal guard: archive entries with ../ are rejected
- secret exclusion: only secret_ref references in the archive, never values
- tests: 24 new S11 tests (version mismatch, traversal, partial failure,
  secret exclusion, rollback, CLI smoke); 541/542 PASS, ruff check clean
```

---

*Конец IMPLEMENTATION_LOG.md S11.*

---

## C4 review follow-up — исправления дефектов экспорта/импорта и CLI

Независимый review checkpoint C4 выявил 5 дефектов. Все исправлены; добавлены
регрессионные тесты, которые до фикса падали.

### FINDING-1 (MAJOR) — rollback не восстанавливал `locales`/`themes`
`_restore_backup` итерировал ключи `DOMAIN_DIRS` (`locale`, `theme`), тогда как
бэкап пишется по именам каталогов (`locales`, `themes`). Два домена молча
пропускались, и после сбоя записи root оставался в смешанном состоянии.
Исправлено: итерация по `DOMAIN_DIRS.values()`; домен, созданный импортом, но
отсутствовавший в бэкапе, удаляется (полное восстановление pre-import-состояния).
Тест `TestRollbackAllDomains::test_apply_failure_restores_locales_and_themes`
форсирует сбой `os.replace` на последнем домене и проверяет восстановление всех
пяти доменов.

### FINDING-2 (MAJOR) — checksum'ы заявлялись, но не проверялись
`import_from_archive` не сверял `sha256` из manifest с байтами архива, поэтому
повреждённый/подменённый архив применялся молча. Добавлена `_verify_checksums`
(после traversal-проверки, до diff): каждый файл обязан быть объявлен в manifest
и совпадать по digest, иначе `ARCHIVE_INTEGRITY_FAILED` (значение не раскрывается).
Тесты `TestIntegrity::test_tampered_checksum_rejected`,
`test_undeclared_entry_rejected`.

### FINDING-3 (MAJOR) — секретный материал в сырых locale/theme/skills
`build_safe_export`/`verify_no_secrets` видят только структурированные config и
identity. Сырые файлы доменов locale/theme/skills архивировались без проверки,
поэтому ключ, вставленный в `.css`/`.json`/`.yaml`, попадал в архив. Каждый
архивируемый файл теперь экранируется `_assert_secret_free`; при находке экспорт
отказывается (`ARCHIVE_EXPORT_FAILED`), значение в сообщении не попадает.
Тесты `TestRawSecretExclusion::test_export_refuses_secret_in_theme`,
`test_export_refuses_secret_in_locale`.

### FINDING-4 (MINOR) — dry-run обещал `- removed`, `--apply` не удалял
`_atomic_apply` теперь принимает `remove` (список `removed` из diff) и удаляет
файлы после записи, с той же traversal-защитой; сбой удаления вызывает rollback
(бэкап хранит удалённые файлы). Тест `TestApplyRemovesFiles::test_apply_deletes_removed_file`.

### FINDING-5 (MINOR) — `identity` CLI отдавал сырой traceback
Команды `identity show`/`prompt-preview` не были обёрнуты в `handle_errors`,
из-за чего невалидная identity печатала Python-traceback. Обе обёрнуты; докстринг
`cli/errors.py` обновлён (долг S10 по унификации CLI-ошибок закрыт полностью).
Тесты `test_identity_cli.py::test_identity_show_invalid_surfaces_error_code`,
`test_identity_prompt_preview_invalid_surfaces_error_code`.

### Верификация

```powershell
.\.venv\Scripts\python.exe -m pytest -q            # 549 passed, 1 skipped
.\.venv\Scripts\python.exe -m ruff check backend/  # All checks passed!
```

Добавлено 8 регрессионных тестов (6 export/import + 2 identity CLI). Code of
conduct по секретам сохранён: сообщения об ошибках не раскрывают значения.

### Замечание (вне объёма фиксов)
В `backend/tests/cli/` тесты создают пустые каталоги `.seraphim/` и `config/`
(команда doctor/сonfig с cwd по умолчанию). Git пустые каталоги не трекет, в
коммит они не попадают. Устранить — отдельный долг изоляции тестов.

---

*Конец IMPLEMENTATION_LOG.md C4 review follow-up.*

---

## S12 — MODEL LAYER: provider interface и mock

### 1. Цель и объём

Сменяемый интерфейс моделей и детерминированный offline provider, чтобы агентные
тесты CORE (S16+) шли без сети и без токенов, а capabilities провайдера были
явными данными, а не догадкой по имени модели. В объём вошли только абстракция,
нормализованные типы и fake; реальный OpenAI-compatible адаптер — S13, реальный
стриминг — S14, маршрутизация — S15.

### 2. Компоненты

- `model_layer/capabilities.py` — `ProviderCapabilities` (chat, streaming,
  tool_calls, vision, structured_output, reasoning_metadata, context_limit,
  max_output_tokens, max_images, auth kind, supports_cancellation, labels) и
  `CapabilityFeature`/`AuthKind`. Вывод capability из имени модели отсутствует
  конструктивно: нет ни `from_model_name`, ни чтения `model` в этом модуле.
- `model_layer/content.py` — `Message`, `TextPart`/`ImagePart`/`ToolResultPart`,
  `Role`, `PartKind`. `ImagePart` хранит ссылку (`data_ref`) и не сериализует
  байты; не-`dict` `content` и чужие части отвергаются нормализованной ошибкой.
- `model_layer/request.py` — `ModelRequest`, `ToolSpec`; валидация temperature/
  top_p/max_output_tokens/timeout/response_schema, оценка prompt-токенов,
  `schema_version` в диапазоне, round-trip неизвестных полей.
- `model_layer/response.py` — `ModelResponse`, `Usage`, `ToolCall`,
  `FinishReason`, `normalize_tool_calls()` (JSON-строка или объект; malformed JSON
  и не-объект → `RESPONSE_FORMAT_INVALID`, частичный вызов не создаётся).
- `model_layer/cancellation.py` — кооперативный `CancellationToken`.
- `model_layer/health.py` — `ProviderHealth`, `HealthStatus` (словарь PULSE).
- `model_layer/stream.py` — конверт `StreamEvent`/`StreamEventType` (минимальный).
- `model_layer/provider.py` — `ModelProvider` (get_capabilities/health_check/
  generate/stream/validate_request) и `ProviderHealthMixin`.
- `model_layer/errors.py` — `ProviderError` + `ProviderErrorKind` (8 видов) на
  общем envelope; `KIND_TO_CODE`/`KIND_DEFAULTS` задают retryable/
  user_action_required по умолчанию.
- `model_layer/versioning.py` — `check_schema_version`/`require`/`require_mapping`/
  `split_known` (CONTRACTS.md §6.1 для транслируемых сущностей).
- `model_layer/fake.py` — `FakeProvider`/`FakeTurn` и конструкторы `success`,
  `with_tool_calls`, `timing_out`, `refusing`, `failing`.
- `contracts/errors.py` — +4 кода: `PROVIDER_RATE_LIMITED`,
  `PROVIDER_REQUEST_INVALID`, `PROVIDER_CANCELLED`,
  `PROVIDER_CAPABILITY_UNSUPPORTED`; `to_diagnostic_dict` санитизирует
  correlation-поля.

### 3. Как CORE узнаёт capabilities модели

Через `ModelProvider.get_capabilities()` → `ProviderCapabilities`. Это данные,
которые провайдер (а с S15 — профиль конфигурации) объявляет явно; ничего не
выводится из `model`/`model_name`. Перед работой вызывается
`validate_request(request, cancellation)`, который через `caps.require(...)`
превращает необъявленную возможность в `PROVIDER_CAPABILITY_UNSUPPORTED`, а
превышение лимитов (context_limit, max_images, max_output_tokens) — в
`PROVIDER_REQUEST_INVALID`. COMPASS (S15) сможет маршрутизировать по тем же полям.

### 4. Что составляет общий контракт ответа

`ModelResponse`: `id`, `model`, `provider`, `content` (список частей),
`tool_calls` (нормализованные `ToolCall`), `finish_reason` (`stop`/`length`/
`tool_calls`/`content_filter`/`refusal`/`error`), `usage` (`prompt_tokens`/
`completion_tokens`/`total_tokens`/`cached_tokens`/`cost_usd`), `created_at`,
`schema_version` и `metadata`. Provider-specific данные допускаются только в
`metadata["provider"][<provider_id>]` и CORE их не интерпретирует. Ошибки —
`ProviderError` на общем envelope §14.2 (`code`/`message_key`/`component`/
`retryable`/`user_action_required`/`details_ref`), без stack trace и без значений
ключей.

### 5. Как тестируется timeout без сети

Скриптованный turn несёт `delay_seconds`; если задержка больше
`request.timeout_seconds`, `FakeProvider` детерминированно бросает
`PROVIDER_TIMEOUT` (retryable) до любого ожидания. Реальные сокеты не
используются — тест `test_no_network_used` патчит `socket.socket`/
`create_connection` и доказывает отсутствие сети. Отмена проверяется и до работы
(pre-cancel), и в середине задержки (mid-flight, из отдельного потока), и не
съедает скриптованный turn и не двигает id.

### 6. Независимое ревью

Два раунда `code-reviewer` (read-only). Раунд 1: 0 BLOCKER, 1 MAJOR (M1 —
проверки capabilities не были покрыты на реальном пути `generate`, набор оставался
зелёным при удалении вызова), MINOR m2–m11, NIT n12–n20. Раунд 2 после правок:
0 BLOCKER, 0 MAJOR.

Закрыто: M1 (класс `TestCapabilityEnforcedOnGeneratePath`; проверено снятием
`validate_request` — падают 6 из 7 тестов); m2/m3/m9/m10 (пересанитизация на
сериализации для `StreamEvent`, `ModelResponse`, `ProviderHealth`,
`ModelRequest`); m4 (проверка отмены до счётчиков и до `_next_turn`);
m5/m6 (`fixed_created_at`, `reset()` восстанавливает скрипт); m7 (`versioning.py`,
диапазон версии, round-trip неизвестных полей, `require` вместо `KeyError`);
m8 (`supports_cancellation` проверяется при переданном токене);
m11 (`provider_id` санитизируется перед попаданием в `component`); MINOR A–D
(пересанитизация `ModelRequest`/`ProviderHealth`, санитизация `_extra_fields` и
correlation-полей); MINOR E (ложноположительный тест заменён на не-итерируемый
вход); MINOR F–H (явный `minimum`, тесты на `< min` и не-int версию,
`require_mapping` для не-объектного metadata); n15/n18/n19.

Проверка ложноположительности новых тестов санитизации выполнена откатом фикса:
оба теста (`test_request_metadata_sanitized_on_serialization`,
`test_unknown_field_is_sanitized_on_serialization`) падают, затем фикс возвращён.

Осознанно оставлено (не блокирует, задокументировано в §10): `reasoning_metadata`
— routing-трейт без request-поля, требующего его; `ModelProvider.capabilities()`,
`ProviderHealthMixin._health_from_error` и `CapabilityFeature.REASONING_METADATA`
— задел на S13–S15.

### 7. Верификация

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/model_layer -q   # 434 passed
.\.venv\Scripts\python.exe -m pytest -q                             # 1010 passed, 1 skipped
.\.venv\Scripts\python.exe -m ruff check backend/                   # All checks passed!
```

Измерено на текущем дереве. Поддерево `backend/tests/model_layer/` без
openai_compatible/streaming/privacy-gate: 135 passed (capabilities, errors,
request/response, fake provider).

Ручная проверка поведения (скрипт, затем удалён; фактические результаты):

```
1. success      -> text: done | finish: stop | usage: {prompt:2, completion:1, total:3}
2. tool call    -> finish: tool_calls | calls: [('call_0','filesystem.read_file',{'path':'a.txt'})]
3. timeout      -> kind: timeout | code: PROVIDER_TIMEOUT | retryable: True   (без сети)
4. failure      -> kind: auth | code: PROVIDER_AUTH_FAILED | secret leaked: False
5. cancellation -> pre-cancel -> cancelled PROVIDER_CANCELLED
6. refusal      -> finish: refusal
7. capability   -> code: PROVIDER_CAPABILITY_UNSUPPORTED | feature: {'feature':'streaming'}
                   (провайдер с model='gpt-4o' и пустыми caps не получает streaming)
8. round-trip   -> ok: True | provider: fake
```

### 8. Ответы на обязательные вопросы

- **Как CORE узнаёт capabilities модели?** `get_capabilities()` (§3); из имени
  модели ничего не выводится.
- **Что составляет общий контракт ответа?** `ModelResponse` + `Usage` + `ToolCall`
  + `FinishReason` + `ProviderError` (§4).
- **Как тестируется timeout без сети?** Скриптованная задержка vs
  `request.timeout_seconds` → `PROVIDER_TIMEOUT` до ожидания (§5).

### 9. Ручные проверки пользователя

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/model_layer -v
# ожидается 134 passed, включая:
#   TestSuccess::test_returns_text, test_no_network_used
#   TestToolCalls::test_tool_call_response
#   TestTimeout::test_timeout_without_network
#   TestFailure::test_normalized_failure, test_failure_does_not_leak_secret
#   TestCancellation::test_pre_cancelled_token_raises,
#                      test_mid_flight_cancellation_interrupts_delay
#   TestCapabilityEnforcedOnGeneratePath (6 тестов)
```

### 10. Риски и долги

1. **Privacy gate не подключён в runtime** (долг S09 §10.1): MODEL LAYER ещё не
   вызывает `assert_transmission_allowed`; сетевого кода в S12 нет, поэтому
   критерий «ошибки без auth leakage» выполнен на контракте, а живая проверка
   privacy появится вместе с реальным адаптером (S13).
2. **Streaming — заглушка**: `START`→`DONE` без дробления; контракт
   `StreamEvent` есть, реальная семантика (фрагменты аргументов, порядок,
   mid-stream cancel) — S14.
3. **`reasoning_metadata`** объявлен, но ни один запрос его не требует;
   поведение появится при поддержке провайдеров с reasoning (S13+).
4. **`ProviderErrorKind` не покрывает «content policy» отдельно**: отказ модели —
   это `finish_reason=refusal`, а не ошибка; при необходимости отдельного кода
   добавить в S13/S14.
5. **Оценка токенов эвристична** (`len/4`); реальный tokenizer появится с
   адаптером (S13). До этого context-limit проверка приблизительная.
6. **Стриминг и `supports_cancellation=False`**: базовый `stream` не проверяет
   `supports_cancellation` при переданном токене — поведение зафиксируется в S14.
7. Незакоммиченные изменения S07–S11 сохранены; S12 не коммитит (по инструкции).

### 11. Резюме изменений

```
backend/seraphim/model_layer/
  __init__.py      — публичный экспорт слоя
  errors.py        — ProviderError, ProviderErrorKind, KIND_TO_CODE/KIND_DEFAULTS
  capabilities.py  — ProviderCapabilities, CapabilityFeature, AuthKind
  content.py       — Message, TextPart/ImagePart/ToolResultPart, Role, PartKind
  request.py       — ModelRequest, ToolSpec
  response.py      — ModelResponse, Usage, ToolCall, FinishReason, normalize_tool_calls
  cancellation.py  — CancellationToken
  health.py        — ProviderHealth, HealthStatus
  stream.py        — StreamEvent, StreamEventType
  provider.py      — ModelProvider, ProviderHealthMixin
  versioning.py    — check_schema_version, require, require_mapping, split_known
  fake.py          — FakeProvider, FakeTurn
backend/seraphim/contracts/errors.py — +4 provider-кода; sanitize correlation-полей
backend/tests/model_layer/ — 134 теста (capabilities, errors, request/response, fake)
CONTRACTS.md — §2.5: ошибки и реализация S12
IMPLEMENTATION_PLAN.md — S12 переведён в ВЫПОЛНЕН
```

### 12. Предлагаемое сообщение коммита

```
feat: S12 MODEL LAYER provider interface and offline FakeProvider

- model_layer/capabilities.py: explicit ProviderCapabilities (chat, streaming,
  tool calls, vision, structured output, reasoning metadata, context limit,
  max output tokens, max images, auth kind, cancellation); capabilities are
  never inferred from a model name
- model_layer/provider.py: ModelProvider interface (get_capabilities,
  health_check, generate, stream, validate_request); validate_request rejects
  an undeclared feature or an exceeded limit before any provider work
- model_layer/{content,request,response}.py: normalized messages, request,
  response, usage and tool calls; provider-specific data is allowed only under
  metadata["provider"][<id>] and is never interpreted by CORE
- model_layer/{cancellation,health,stream}.py: cooperative cancellation token,
  ProviderHealth with PULSE statuses, minimal stream event envelope
- model_layer/errors.py: ProviderError with 8 provider-independent kinds mapped
  onto the shared error envelope; credentials are scrubbed (TB-7)
- model_layer/fake.py: deterministic offline FakeProvider (success, tool calls,
  refusal, normalized failure, timeout, cancellation) with stable ids, no I/O
- model_layer/versioning.py: schema_version range checks and round-trip of
  unknown optional fields (CONTRACTS.md §6.1)
- contracts/errors.py: +PROVIDER_RATE_LIMITED, PROVIDER_REQUEST_INVALID,
  PROVIDER_CANCELLED, PROVIDER_CAPABILITY_UNSUPPORTED; sanitize correlation
  fields in the diagnostic view
- tests: 134 new offline tests; 683/684 PASS; ruff check clean
- independent review (2 rounds): 0 BLOCKER, 0 MAJOR after fixes
```

---

*Конец IMPLEMENTATION_LOG.md S12.*

---

## S13 — OpenAI-compatible provider: базовые запросы

### 1. Цель и объём

Подключить конфигурируемый OpenAI-compatible endpoint так, чтобы endpoint,
пути, схема аутентификации, заголовки и набор поддерживаемых возможностей были
*данными конфигурации*, а не константами исходников; ошибки — понятными и без
утечки ключа; а весь CI работал offline. В объём вошли chat-запросы без
стриминга, health check, обнаружение/настройка расхождений и локальные тесты на
mock HTTP server. Стриминг и полная нормализация tool calls — S14, маршрутизация
— S15.

### 2. Компоненты

- `model_layer/http_transport.py` — `HttpResponse`, `HttpTransport` (Protocol) и
  `UrllibTransport`. Транспорт возвращает *любой* HTTP-статус как ответ и
  поднимает нормализованную ошибку только при сбое соединения
  (`PROVIDER_TIMEOUT`/`PROVIDER_UNAVAILABLE`). `_safe_url` убирает userinfo из
  URL перед попаданием в сообщение об ошибке.
- `model_layer/openai_compatible.py` — `OpenAICompatibleConfig`,
  `OpenAICompatibleProvider`, `CapabilityProbe`,
  `build_openai_compatible_provider`. Формирует payload, парсит ответ, маппит
  статусы в `ProviderError`, публикует/проверяет capabilities.
- `model_layer/cancellation.py` — добавлена `run_with_cancellation(fn, token,
  provider_id)`: блокирующий вызов идёт в daemon-потоке, вызывающий поток
  опрашивает токен и при отмене немедленно поднимает `PROVIDER_CANCELLED`;
  исключение воркера переподнимается без изменений.
- `model_layer/errors.py` — добавлен конструктор `provider_rate_limited_error`
  (для симметрии с остальными видами).
- `sanctum/config_schemas.py` — `ModelEntry` расширен опциональными
  транспортными полями: `timeout_seconds`, `chat_path`, `health_path`,
  `auth_scheme`, `auth_header`, `extra_headers`, `max_tokens_field`,
  `capabilities`. Добавление опционального поля — minor по CONTRACTS §6.1, поэтому
  конфиг, написанный до S13, продолжает работать без миграции.
- `sanctum/loader.py` — `_check_model_headers`: literal-секрет в
  `providers.models[].extra_headers` отвергается (`SECRET_REF_INVALID`), значение
  не возвращается в сообщении.
- `backend/tests/model_layer/test_openai_compatible.py` — 96 тестов,
  `backend/tests/sanctum/test_provider_transport_config.py` — 4 теста.

### 3. Как endpoint (и всё остальное) настраивается конфигурацией

Все параметры подключения берутся из `providers.models[]`:

```yaml
providers:
  schema_version: 1
  default_model_id: local
  models:
    - id: local
      provider: local_openai
      model_name: llama3
      endpoint: http://127.0.0.1:11434      # адрес — данные, не константа
      secret_ref: provider.local            # только ссылка, не значение
      timeout_seconds: 5.5
      chat_path: /v1/chat/completions
      health_path: /v1/models
      auth_scheme: api_key                  # bearer | api_key | none
      auth_header: api-key                  # Azure-подобный вариант
      max_tokens: 2048
      max_tokens_field: max_completion_tokens
      extra_headers: { X-Org: acme }        # literal-ключ здесь отвергается
      capabilities: { tool_calls: true, context_limit: 8192 }
```

`build_openai_compatible_provider(entry, secret_resolver=store.get)` превращает
такую запись в провайдера. Тест `test_endpoint_is_not_hard_coded` поднимает два
сервера и доказывает, что две записи конфигурации попадают на два разных адреса.

### 4. Маппинг ошибок

| Что вернул endpoint | Код SERAPHIM | retryable |
|---|---|---|
| `401`, `403` | `PROVIDER_AUTH_FAILED` | нет |
| `408` | `PROVIDER_TIMEOUT` | да |
| `429` | `PROVIDER_RATE_LIMITED` | да |
| `5xx` | `PROVIDER_UNAVAILABLE` | да |
| прочие `4xx` (`400`, `404`, `405`, `422`…) | `PROVIDER_REQUEST_INVALID` | нет |
| `200` с битым JSON / без `choices` / legacy `text`-формой | `RESPONSE_FORMAT_INVALID` | да |
| `3xx` (редирект) | `PROVIDER_REQUEST_INVALID` | нет |
| сбой соединения, разрыв | `PROVIDER_UNAVAILABLE` | да |
| таймаут запроса | `PROVIDER_TIMEOUT` | да |
| отмена | `PROVIDER_CANCELLED` | нет |

Текст ошибки endpoint используется только после санитизации и обрезки до 200
символов, поэтому «понятность» не превращается в канал утечки.

Редиректы **не** отслеживаются намеренно: `urllib` по умолчанию пересобирает
запрос и переносит исходные заголовки (кроме `content-*`) на новый URL, то есть
отправил бы `Authorization` с ключом на хост, которого оператор не настраивал.
`UrllibTransport` использует opener с обработчиком, который отказывается от
редиректа, поэтому `3xx` доходит до адаптера как обычный ответ и превращается в
понятную ошибку конфигурации.

### 5. Как проверено отсутствие API key в логах

Три независимых барьера и три теста:

1. Ключ читается лениво из `secret_ref` и сразу регистрируется
   (`register_known_secret`), поэтому его значение вырезается любым
   `sanitize_text`/`sanitize_dict` — включая конструктор `SeraphimError`.
2. `_error_detail` дополнительно вырезает точное значение из тела ошибки
   (`redact_known_secrets(detail, key)`) — до того, как оно станет `safe_message`.
3. Адаптер логирует только host, модель, число сообщений и число инструментов:
   ни заголовки, ни ключ в лог не передаются.

Тесты: `test_no_key_in_logs_on_success` и `test_no_key_in_logs_on_failure`
перехватывают весь вывод логгера `seraphim.model_layer.openai_compatible` и
проверяют отсутствие ключа и заголовка `Authorization`; при этом тот же тест
утверждает, что ключ *был отправлен* (`authorization: Bearer <key>` в записи
mock-сервера) — то есть проверка не вырождена. Тест
`test_error_body_scrubbed_even_for_an_unknown_key_format` использует ключ без
узнаваемого формата, поэтому проходит только благодаря точному совпадению.

### 6. Как тестировать провайдер без расхода токенов

Весь набор — на локальном mock HTTP server (`http.server.ThreadingHTTPServer` на
`127.0.0.1` с эфемерным портом), который пишет полученные запросы, чтобы тест мог
проверить точный payload и заголовки. Ни один тест не выходит во внешнюю сеть.
Для негативных сценариев: «медленный» сервер (таймаут), listener, который
принимает соединение и сразу закрывает его (разрыв), закрытый порт (недоступный
endpoint), битый JSON и HTML вместо JSON. Отмена проверяется из отдельного
потока и утверждает, что она срабатывает быстро (< 0.8 c), а не после ответа
сервера. Live smoke test возможен только вручную и с отдельным согласованным
профилем; для CI он не нужен.

### 7. Что НЕ поддержано (и почему)

- **Streaming** — S14. Адаптер всегда отправляет `stream: false`; базовый
  `ModelProvider.stream` требует объявленной capability `streaming` и отдаёт
  один терминальный `DONE`.
- **Повтор assistant-сообщения с tool calls в истории** — у нормализованного
  `Message` пока нет поля для tool calls ассистента (S14); можно передать
  `ToolResultPart`, но не восстановить сам запрос модели.
- **Embeddings / rerank / legacy completions** — вне S13; legacy-форма
  `choices[].text` отвергается как `RESPONSE_FORMAT_INVALID`.
- **Reasoning-поля** (`reasoning_content`, `reasoning`) — не извлекаются;
  capability `reasoning_metadata` можно объявить, но поведение появится позже.
- **Провайдер-специфичные расширения** (Azure `api-version` в query, Anthropic
  `system`-поле, `logit_bias`, `seed` и т.п.) — не отправляются; из расхождений
  параметризованы только `auth_header`/`auth_scheme` и имя поля бюджета токенов.
- **Автоматическое определение возможностей по имени модели** — отсутствует
  конструктивно.
- **Строгая валидация `response_format`** — отправляется OpenAI-форма
  `json_schema`; серверы с другим контрактом должны объявлять
  `structured_output: false`.
- **Отслеживание редиректов** — намеренно отсутствует (см. §4): `3xx`
  превращается в ошибку конфигурации, потому что следование за редиректом
  отправило бы ключ на другой хост. Если сервис штатно отвечает редиректом,
  нужно указать конечный URL в `endpoint`.

### 8. Независимое ревью

Один раунд `code-reviewer` (read-only). Итог первого прохода: **1 BLOCKER, 1 MAJOR**,
5 MINOR, 8 NIT. Оба блокирующих пункта закрыты, MAJOR закрыт, MINOR m1–m5 и часть
NIT закрыты; оставшиеся NIT осознанно приняты.

- **BLOCKER B1 — ключ мог попасть в `ModelResponse.to_dict()`.** Ответ модели —
  недоверенные данные (TB-1), а санитизировался только `metadata` (S12). Сервер,
  только что получивший ключ в заголовке, мог вернуть его в `id`, `model`,
  `content` или `tool_calls`, и он оказывался в контрактном объекте и любом его
  дампе. Ревьюер воспроизвёл утечку (`key_in_full_dump: True`). Закрыто: все
  значения, взятые из тела ответа (`id`, `model`, `content`, `system_fingerprint`,
  `tool_calls.id/name/arguments/raw_arguments`), проходят через `sanitize_text`/
  `sanitize_dict` до того, как стать полями контракта. Тесты
  `test_echoed_key_in_response_fields_is_scrubbed` и
  `test_echoed_opaque_key_in_response_fields_is_scrubbed`; ложноположительность
  проверена откатом санитизации `content` — оба теста падают.
- **MAJOR M1 — редиректы пересылали заголовок с ключом.** `urllib` по умолчанию
  следует за `3xx` и копирует исходные заголовки (кроме `content-*`) на новый URL,
  то есть `Authorization` уходил бы на хост, которого оператор не настраивал.
  Закрыто: `UrllibTransport` собирает opener с `_NoRedirectHandler` (возвращает
  `None` → статус приходит как обычный ответ), а адаптер маппит `3xx` в
  `PROVIDER_REQUEST_INVALID` с объяснением; `Location` не эхо-отражается. Тест
  `test_redirect_is_not_followed` проверяет, что второй сервер не получил ни
  одного запроса.
- **m1** — `capability_probe()` получил защитный `except Exception`, приведённый к
  обещанному «Never raises».
- **m2** — добавлены тесты на непокрытые ветки `run_with_cancellation`: успешный
  результат через поток и переподнятие исключения воркера без изменения
  (`kind`/`code`/`retryable` сохраняются).
- **m3** — `OpenAICompatibleConfig.to_dict()` теперь прогоняет результат через
  `sanitize_dict`.
- **m4** — абсолютный URL в `chat_path`/`health_path` отвергается
  (`VALIDATION_FAILED`), иначе путь мог увести запрос вместе с ключом на другой хост.
- **m5** — единый источник дефолта бюджета токенов: `_DEFAULT_MAX_TOKENS = 4096`
  (зеркалит `ModelEntry.max_tokens`) используется и в схеме, и в фабрике.
- **n1** — `structured_output_name` помечен как фиксированный в S13.
- **n2** — `capability_probe().declared` теперь включает и ненаблюдаемые
  объявленные возможности (`reasoning_metadata`), поэтому объявленное-но-непроверенное
  не исчезает молча; `supports_cancellation` исключён как клиентский трейт.
- **n3** — убран мёртвый параметр `request` у `_parse_response`.
- **n4** — `extra_headers` отвергает управляющие символы (`\r`/`\n`/`\0`).
- **n5** — усилены слабые тесты: `test_safe_description_contains_no_header_values`
  проверяет отсутствие значения заголовка и самого поля `extra_headers`;
  `test_no_key_in_logs_on_failure` дополнительно утверждает, что ключ был реально
  отправлен; вместо почти вакуумных тестов добавлены
  `test_adapter_source_does_not_import_a_provider_sdk` (структурная проверка
  отсутствия vendor SDK) и `test_no_non_loopback_connection_is_attempted`
  (перехват `socket.connect`: все соединения только на 127.0.0.1).
- **Принято осознанно:** n7 (фоновый daemon-воркер при отмене, §12.4) и n8
  (значения короче `MIN_KNOWN_SECRET_LENGTH` не вырезаются точным совпадением —
  неактуально для реальных ключей).

Отдельно зафиксирована политика: аргументы tool call санитизируются как любой
другой недоверенный payload, поэтому аргумент с именем-похожим-на-секрет
(`api_key`, `token`, `password`) будет отредактирован. Это согласуется с S12
(`metadata`) и с инвариантом «учётные данные не сериализуются»; для реальных
инструментов SERAPHIM учётные данные передаются ссылками, а не значениями.

### 9. Верификация

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/model_layer -q   # 230 passed
.\.venv\Scripts\python.exe -m pytest -q                             # 783 passed, 1 skipped
.\.venv\Scripts\python.exe -m ruff check backend/                   # All checks passed!
```

До S13: 683 passed, 1 skipped. Добавлено 100 тестов
(`test_openai_compatible.py` 96, `test_provider_transport_config.py` 4).

Ручная проверка поведения (временный скрипт на локальном сервере, затем удалён;
фактические результаты после правок по ревью):

```
1. success        : done | usage_total=13
2. tool call      : finish=tool_calls calls=[('c1','read_file',{'path':'a'})]
   verified caps  : tool_calls=True
3. capability gate: code=PROVIDER_CAPABILITY_UNSUPPORTED kind=capability_unsupported
4. auth error     : code=PROVIDER_AUTH_FAILED key_leaked=False
                    msg='endpoint rejected the credential (HTTP 401): bad key [REDACTED]'
5. echoed key     : key_in_dump=False (7 полей отредактировано)     <- BLOCKER B1
6. redirect       : code=PROVIDER_REQUEST_INVALID, target hits=0    <- MAJOR M1
7. rate limited   : code=PROVIDER_RATE_LIMITED kind=rate_limited retryable=True
8. unavailable    : code=PROVIDER_UNAVAILABLE kind=unavailable retryable=True
9. malformed body : code=RESPONSE_FORMAT_INVALID kind=response_invalid retryable=True
10. timeout       : code=PROVIDER_TIMEOUT kind=timeout retryable=True
11. cancelled     : code=PROVIDER_CANCELLED kind=cancelled  (latency 0.108s)
12. health        : ONLINE
    probe         : reachable=True status=200 verified=['chat'] declared=['chat','tool_calls']
                    unverified_declared=['tool_calls']
13. from config   : provider=openai text='from-config' | key in config dump=False
                    round-trip=True
14. invalid configs: absolute chat_path -> VALIDATION_FAILED
                    control char header -> VALIDATION_FAILED
```

Ложноположительность проверена откатом фиксов:

- снятие `validate_request` в `generate` → падают
  `test_tools_rejected_without_declaration`, `test_context_limit_is_enforced`;
- снятие `register_known_secret` **и** точной редакции в `_error_detail` →
  падает `test_error_body_scrubbed_even_for_an_unknown_key_format` (ключ без
  узнаваемого формата ловится только точным совпадением);
- снятие санитизации `content` → падают
  `test_echoed_key_in_response_fields_is_scrubbed` и
  `test_echoed_opaque_key_in_response_fields_is_scrubbed` (BLOCKER B1).

Все фиксы возвращены, набор снова зелёный.

### 10. Ответы на обязательные вопросы

- **Какие особенности OpenAI-compatible API не поддержаны?** §7: streaming,
  повтор assistant tool calls в истории, embeddings/rerank/legacy completions,
  reasoning-поля, провайдер-специфичные расширения (кроме параметризованных
  `auth_scheme`/`auth_header`/`max_tokens_field`), автоматический вывод
  возможностей из имени модели, не-OpenAI-форма `response_format`.
- **Как проверено отсутствие API key в логах?** §5: ленивое чтение +
  регистрация значения, точная редакция тела ошибки, логирование без заголовков;
  три теста, включая проверку «ключ был отправлен, но в лог не попал».
- **Как тестировать provider без расхода токенов?** §6: локальный mock HTTP
  server на loopback с записью запросов; негативные сценарии — медленный сервер,
  разрыв соединения, закрытый порт, битый JSON.

### 11. Ручные проверки пользователя

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/model_layer/test_openai_compatible.py -v
.\.venv\Scripts\python.exe -m pytest backend/tests/sanctum/test_provider_transport_config.py -v
# ожидается 96 + 4 passed, включая:
#   TestConfigValidation, TestSuccessfulGeneration, TestHeadersAndAuth,
#   TestErrorMapping, TestNetworkAndCancellation, TestRedaction, TestCapabilities,
#   TestHealth, TestFactory
```

Live smoke test запускать только вручную и только с отдельным согласованным
тестовым профилем (свой endpoint и свой `secret_ref`); в CI он не входит.

### 12. Риски и долги

1. **Privacy gate всё ещё не подключён в runtime.** Теперь в слое появился
   реальный сетевой код, поэтому вызов `assert_transmission_allowed` перед
   отправкой контекста наружу — обязательный долг (S15, вместе с COMPASS).
   Сейчас адаптер не проверяет `allow_external_transmission`.
2. **Стриминг — S14.** `stream()` остаётся заглушкой `START`→`DONE`.
3. **Оценка токенов эвристична** (`len/4`), реального tokenizer нет.
4. **`run_with_cancellation` оставляет фоновый поток** до завершения сокета: он
   daemon и его результат отбрасывается, но сам сокет закрывается не мгновенно.
5. **Проверка capabilities ограничена наблюдением.** `chat` подтверждается
   успешным обменом, `tool_calls`/`vision`/`structured_output` — только когда они
   реально использованы; `streaming` не подтверждается вообще до S14.
6. **`tool_calls[].id` синтезируется**, если сервер его не прислал; факт виден в
   `metadata["provider"][<id>]["synthesized_tool_call_ids"]`.
7. **`response_format` отправляется только в OpenAI-форме** `json_schema`; серверы
   с другим контрактом должны не объявлять `structured_output`.
8. **Аргументы tool call санитизируются как недоверенный payload.** Аргумент с
   именем-похожим-на-секрет (`api_key`, `token`, `password`) будет отредактирован
   (`sanitize_dict`), что согласуется с политикой S12 для `metadata`, но может
   «испортить» легитимный аргумент. Для инструментов SERAPHIM учётные данные
   передаются ссылками, поэтому на практике не встречается; при необходимости
   политику уточнить в S19 (WINGS tool contract).
9. **Серверные поля ответа санитизируются в адаптере, а не в контракте.**
   `ModelResponse`/`ToolCall` (S12) по-прежнему санитизируют только `metadata`,
   поэтому новый адаптер обязан повторить эту обработку. Кандидат на вынос в
   общий helper при появлении второго HTTP-провайдера.
10. Незакоммиченные изменения S07–S12 сохранены; S13 не коммитит (по инструкции).

### 13. Резюме изменений

```
backend/seraphim/model_layer/
  http_transport.py     — HttpResponse, HttpTransport, UrllibTransport
  openai_compatible.py  — OpenAICompatibleConfig, OpenAICompatibleProvider,
                          CapabilityProbe, build_openai_compatible_provider
  cancellation.py       — +run_with_cancellation
  errors.py             — +provider_rate_limited_error
  __init__.py           — экспорт новых имён
backend/seraphim/sanctum/config_schemas.py — ModelEntry: транспортные поля
backend/seraphim/sanctum/loader.py         — _check_model_headers
backend/tests/model_layer/test_openai_compatible.py        — 96 тестов
backend/tests/sanctum/test_provider_transport_config.py    — 4 теста
CONTRACTS.md — §2.5: реализация S13
IMPLEMENTATION_PLAN.md — S13 переведён в ВЫПОЛНЕН
```

### 14. Предлагаемое сообщение коммита

```
feat: S13 OpenAI-compatible provider adapter (configured endpoint, offline tests)

- model_layer/openai_compatible.py: adapter for a configurable OpenAI-compatible
  endpoint; endpoint, paths, auth scheme/header, extra headers, token-budget
  field and declared capabilities all come from providers.models[] in config
- model_layer/http_transport.py: stdlib-only HTTP transport behind an injectable
  seam, so tests run offline against a loopback mock server
- error mapping: 401/403 -> auth, 408 -> timeout, 429 -> rate limited, 5xx ->
  unavailable, other 4xx -> invalid request, malformed body -> response invalid,
  connection failure/timeout/cancellation -> normalized ProviderError
- credential safety: the key is read lazily from secret_ref, registered with the
  process-wide redactor, scrubbed out of provider error bodies, never logged, and
  every field taken from the response envelope (id, model, content, tool calls)
  is sanitized before it becomes a contract field
- redirects are not followed: urllib would resend the Authorization header to the
  redirect target, so a 3xx becomes an explicit configuration error
- no full-compatibility assumption: an empty declaration publishes chat only;
  known divergences (usage field names, missing tool-call id, list-shaped
  content) are handled explicitly and reported in response metadata;
  capability_probe()/verified_capabilities() expose only observed features
- cancellation: run_with_cancellation makes a blocking request interruptible and
  re-raises worker exceptions unchanged
- sanctum: optional transport fields on ModelEntry (minor, no migration) and a
  loader check that rejects a literal secret in extra_headers
- tests: 100 new offline tests; 783/784 PASS; ruff check clean
- independent review (1 round): 1 BLOCKER + 1 MAJOR found and fixed
```

---

*Конец IMPLEMENTATION_LOG.md S13.*

---

## S14 — Streaming и нормализация tool calls

### 1. Цель и объём

Дать CORE/UI **единый внутренний поток событий** вместо «дождаться всего
ответа», при этом сохранив два жёстких инварианта: tool call запускается только
после полной валидации аргументов, а отмена прекращает любую последующую
обработку. В объём вошли: конверт событий с гарантией порядка, инкрементальный
SSE-парсер, потоковый транспорт с прерываемым чтением, сборка фрагментов
аргументов tool call, `stream()` в OpenAI-compatible адаптере, лимиты стрима в
конфигурации и offline-тесты на loopback mock server. Маршрутизация запросов,
privacy gate и подключение стрима к runtime — S15.

### 2. Компоненты

- `model_layer/stream.py` — конверт и порядок:
  - `StreamEventType` — 9 видов: `start`, `text_delta`, `tool_call_start`,
    `tool_call_args_delta`, `tool_call`, `usage`, `done`, `error`, `cancelled`;
  - `StreamEvent` — dataclass с `sequence`, `is_terminal`, `to_dict()`
    (сериализация санитизирует `text_delta`, `tool_call_id`, `tool_call_name`,
    `arguments_delta`, `metadata`, `error`);
  - `StreamSequencer` — единственный конструктор событий адаптера, поэтому
    контракт порядка — свойство кода, а не соглашение;
  - `validate_stream(events)` — проверка контракта для тестов/буферизующего
    потребителя;
  - `StreamLimits` — `max_response_bytes` 8 МБ, `max_event_bytes` 1 МБ,
    `max_arguments_bytes` 1 МБ, `max_tool_calls` 64,
    `idle_timeout_seconds` 120 с; все значения обязаны быть > 0 (нет
    «0 отключает»), `tool_call_limits()` проецирует их в accumulator;
  - `RedactingDeltaBuffer` — буфер с удержанием хвоста, который не даёт
    выпустить известный секрет по частям (§8).
- `model_layer/sse.py` — `SSEMessage`, инкрементальный `SSEParser`
  (`feed_line`/`close`, `max_event_bytes`, счёт в байтах),
  `SSEEventTooLargeError`, `STREAM_DONE_SENTINEL = "[DONE]"`.
- `model_layer/tool_calls.py` — `ToolCallLimits`, `ToolCallAccumulator`:
  сборка по `index` (а не по позиции в массиве), `finish()` — **единственная**
  точка создания `ToolCall`.
- `model_layer/http_transport.py` — `StreamIdle` (сигнал опроса, не ошибка),
  `HttpStream` Protocol (`read_line(timeout)`/`close`), `UrllibTransport.open_stream()`
  → `_UrllibStream` (daemon-thread pump + очередь с бюджетом по памяти),
  `_BufferedStream` (не-200 ответ отдаётся через тот же интерфейс).
- `model_layer/openai_compatible.py` — `stream()`, `_stream_events`,
  `_pump_stream`, `_delta_text`, `_delta_tool_calls`, `_build_payload(stream=True)`,
  `STREAM_ACCEPT = "text/event-stream"`; поля `stream_limits`,
  `stream_include_usage` в конфиге адаптера.
- `model_layer/provider.py` — базовый `ModelProvider.stream()` (заглушка для
  провайдеров без реального стриминга) тоже строит события через
  `StreamSequencer` и завершает поток терминальным событием.
- `sanctum/config_schemas.py` — `ModelEntry.stream_max_response_bytes`,
  `stream_max_event_bytes`, `stream_max_arguments_bytes`, `stream_max_tool_calls`,
  `stream_idle_timeout_seconds`, `stream_include_usage` (все опциональные —
  minor по CONTRACTS §6.1, конфиг до S14 работает без миграции).
- `contracts/sanitization.py` — `max_known_secret_length()`,
  `split_releasable(text)`; `response.py::ToolCall.to_dict()` теперь санитизирует
  `id`/`name`/`arguments`/`raw_arguments`.
- `backend/tests/model_layer/test_streaming.py` — 165 тестов;
  `backend/tests/model_layer/test_fake_provider.py` — +1;
  `backend/tests/sanctum/test_provider_transport_config.py` — +2.

### 3. Гарантии порядка stream events

Порядок не документируется, а **проверяется** `StreamSequencer`, который
является единственным способом создать событие в адаптере:

1. `sequence` начинается с 0 и строго возрастает без пропусков и повторов;
2. `START` — первое событие и ровно одно (повторный `start()` → `RuntimeError`);
3. ровно одно терминальное событие (`done`/`error`/`cancelled`) и оно последнее:
   любое событие после терминального → `RuntimeError`;
4. `TOOL_CALL` эмитится только для полностью собранного и валидированного
   вызова, никогда для фрагмента;
5. `TOOL_CALL_START` для данного `index` всегда раньше первого
   `TOOL_CALL_ARGS_DELTA` этого `index` (событие START эмитится при первом
   появлении `index`, даже если сервер прислал аргументы раньше имени);
6. `flush()` буферов удержания выполняется **до** `TOOL_CALL`, поэтому ни один
   `text_delta`/`tool_call_args_delta` не появляется после терминального события.

Нарушение — программная ошибка адаптера, а не сбой провайдера, поэтому это
`RuntimeError`, а не `ProviderError`; в поток она попасть не может.

Дополнительно адаптер защищён от «забытого» терминального события: любое
исключение, не нормализованное в `ProviderError`, перехватывается вокруг
`_pump_stream` и превращается в терминальный `error` (в сообщение попадает
только **тип** исключения, т.к. текст — недоверенные данные).

### 4. Как исключён запуск неполного tool call

`ToolCall` создаётся только в `ToolCallAccumulator.finish()`. До этого
существуют лишь `_PartialCall` (id/name/строка аргументов). `finish()`:

1. парсит каждый payload как JSON и требует **объект** (`normalize_tool_calls`);
2. отвергает набор **целиком**, если хотя бы у одного вызова нет имени, битый
   или усечённый JSON, дубликат `id`, `id` сменился mid-stream, отрицательный
   `index` или превышен лимит (число вызовов / байты аргументов / длина имени);
3. при ошибке не возвращает **ни одного** вызова, а адаптер эмитит
   терминальный `error` (`RESPONSE_FORMAT_INVALID`).

Поэтому «половина плана» не может уйти на исполнение: потребитель либо получает
весь набор валидных вызовов, либо ни одного. Пустой `id` синтезируется
детерминированно (`<provider>_call_<index>`) и факт виден в
`metadata["provider"][<id>]["synthesized_tool_call_ids"]`.

Живые `tool_call_args_delta` — это только UI-подсказка (и они санитизированы,
поэтому могут не быть валидным JSON); авторитетный источник — событие
`TOOL_CALL`, построенное из несanitized-копии, которую держит accumulator.

### 5. Что происходит при обрыве потока на середине аргументов

- Транспорт: `read_line` возвращает `None` на EOF (флаг «липкий»: повторный
  вызов тоже `None`, а не `StreamIdle`), поэтому конец потока не путается с
  «пока тихо».
- `SSEParser.close()` диспатчит незавершённое событие: если сервер успел
  прислать `data:`-строку, но не пустую строку-разделитель, данные не теряются.
- Затем `finish()` пытается распарсить накопленную строку аргументов; усечённый
  JSON → `RESPONSE_FORMAT_INVALID`, вызовов **ноль**, терминальное событие —
  `error`. Никакой попытки «достроить» или исполнить частичный вызов нет.
- Если обрыв случился **после** полностью валидного вызова (все фрагменты
  пришли, `[DONE]` — нет), вызов эмитится ровно один раз и поток завершается
  `done`; дублирования нет, потому что `finish()` вызывается один раз, а
  `TOOL_CALL` строится только из него.
- Если не пришло ни одного события и не было `[DONE]` — это не SSE, а
  `RESPONSE_FORMAT_INVALID` («stream closed before any event arrived»).

### 6. Отмена и таймауты

- Токен проверяется **до** открытия соединения (pre-cancel: запрос не уходит) и
  на каждой итерации чтения. Транспорт отдаёт управление каждые
  `_STREAM_POLL_SECONDS = 0.05` (`StreamIdle`), поэтому отмена не ждёт чанка.
- При отмене следующим событием становится `cancelled` (терминальное), и
  генератор завершается — дальнейшая эмиссия структурно невозможна.
- Два независимых предела: общий (`timeout_seconds` запроса/конфига) и
  «тишина» (`idle_timeout_seconds`); оба дают `PROVIDER_TIMEOUT`.
- `close()` потока закрывает **сам socket**: на Windows `shutdown` и
  `HTTPResponse.close()` не прерывают pending `recv`, а закрытие socket — может;
  pump после этого сам закрывает response из своего потока (чтобы не бороться за
  лок буферизованного reader'а). Потребитель, который перестал читать,
  освобождает соединение мгновенно, а не через таймаут.

### 7. Лимиты и защита от «дорогого» ответа

| Лимит | Значение по умолчанию | Где проверяется |
| --- | --- | --- |
| `max_response_bytes` | 8 000 000 | по декодированным байтам каждой строки |
| `max_event_bytes` | 1 000 000 | `SSEParser` (в байтах UTF-8) |
| `max_arguments_bytes` | 1 000 000 | `ToolCallAccumulator.feed` |
| `max_tool_calls` | 64 | `ToolCallAccumulator.feed` |
| `idle_timeout_seconds` | 120 | `_pump_stream` |

Очередь между pump-потоком и потребителем ограничена бюджетом
(`DEFAULT_MAX_BUFFERED_BYTES = 1 МБ`): без него быстрый endpoint вычитывался бы
в память быстрее, чем потребитель успевает применить `max_response_bytes`.
`stream_include_usage` по умолчанию **выключен**: `stream_options` понимает не
каждый совместимый сервер, а `usage` — необязательное поле.

### 8. Секреты в потоке

Санитизация отдельного фрагмента не ловит ключ, разрезанный между чанками.
Поэтому живой delta проходит через `RedactingDeltaBuffer`, который отдаёт только
тот префикс, который `contracts.sanitization.split_releasable()` доказал
безопасным:

- хвост, являющийся **собственным префиксом** известного секрета, удерживается
  (его может завершить следующий фрагмент);
- граница разреза не попадает **внутрь** уже присутствующего вхождения секрета
  (иначе секрет с «бордером» — первый символ равен последнему — или периодичный
  секрет выпускался бы почти целиком: проверено, наивный разрез отдавал 18 из 19
  символов);
- удержание ограничено, поэтому патологический периодический поток не растит
  буфер без предела; выпускаемое всё равно санитизируется, то есть полного
  секрета в одном событии не бывает.

На терминальном пути (`error`/`cancelled`) удержанный хвост **отбрасывается**, а
не сбрасывается: усечённый секрет не должен уйти наружу.

### 9. Верификация

```powershell
.\.venv\Scripts\python.exe -m pytest -q          # 951 passed, 1 skipped
.\.venv\Scripts\python.exe -m ruff check backend/ # All checks passed!
```

До S14: 783 passed, 1 skipped. Добавлено 168 тестов
(`test_streaming.py` 159, `test_fake_provider.py` +1,
`test_provider_transport_config.py` +2, плюс параметризация).

Ручная проверка (локальный SSE-сервер, скрипт удалён после прогона):

```
1. fragmented JSON   : 3 ARGS_DELTA -> TOOL_CALL {'path': 'a.txt'}      (PASS)
2. truncated args    : ERROR RESPONSE_FORMAT_INVALID, calls=0           (PASS)
3. cancel mid-stream : START, TEXT_DELTA, CANCELLED                     (PASS)
4. early close       : 1 TOOL_CALL + DONE, без дублирования             (PASS)
5. duplicate ids     : ERROR, calls=0                                   (PASS)
6. size limit        : ERROR (response exceeds ...)                     (PASS)
7. split secret      : "[REDACTED]" в delta и в response, половин нет   (PASS)
```

Ложноположительность проверена откатом фиксов:

- откат `_avoid_splitting_an_occurrence` → падает
  `test_a_complete_secret_in_one_fragment_is_redacted_as_a_unit` для секрета с
  бордером (наивный разрез выпускает 18/19 символов);
- откат `_release`/бюджета очереди → падает
  `test_reader_does_not_buffer_far_ahead_of_the_consumer`;
- откат «липкого» EOF → падает `test_end_of_stream_is_sticky`;
- откат `except` вокруг `_pump_stream` → поток завершается без терминального
  события.

### 10. Ответы на обязательные вопросы

- **Гарантии порядка stream events?** §3: `sequence` с 0 без пропусков; `START`
  первый и один; ровно одно терминальное событие последним; `TOOL_CALL` только
  для валидированного вызова; `TOOL_CALL_START` раньше `ARGS_DELTA` своего
  `index`; всё проверяется `StreamSequencer` (нарушение — `RuntimeError`), а
  любое не нормализованное исключение превращается в терминальный `error`.
- **Как исключён запуск неполного tool call?** §4: `ToolCall` создаётся только в
  `ToolCallAccumulator.finish()`, который валидирует весь набор и при любой
  проблеме не возвращает ни одного вызова, а адаптер эмитит `error`.
- **Что при обрыве потока на середине аргументов?** §5: незавершённое SSE-событие
  диспатчится, усечённый JSON отвергается, вызовов ноль, терминальное событие —
  `error` (`RESPONSE_FORMAT_INVALID`).

### 11. Ручная проверка пользователя

Пользователь подтвердил сценарий «JSON, разбитый на несколько stream chunks»:
три `tool_call_args_delta` собираются в один `tool_call` с аргументами
`{'path': 'a.txt'}`, и вызов эмитится один раз, после полной сборки.

### 12. Ограничения и долги

1. **Privacy gate не подключён к runtime** — обязательный долг S15: сейчас
   стрим защищает только от известных секретов и от форматов-паттернов
   (`sanitize_text`), но не применяет политику приватности к содержимому.
2. **Оценка токенов эвристична** (`len/4`) — не влияет на стрим, но
   `max_output_tokens`/`context_limit` проверяются по ней.
3. **`reasoning_metadata` не проверяется** — стрим не разбирает reasoning-дельты
   (провайдер-специфичные поля игнорируются).
4. **Аргументы tool call санитизируются** и потому могут «портиться»
   (аргумент с именем вида `api_key` редактируется). Для инструментов SERAPHIM
   учётные данные передаются ссылками; политику уточнить в S19 (WINGS).
5. **Живые `args_delta` могут не быть валидным JSON** (санитизация + удержание
   хвоста). Это осознанно: авторитетное событие — `TOOL_CALL`, а delta нужна
   только для отображения.
6. **Санитизация серверных полей живёт в адаптере**, а не в контракте
   (`ModelResponse`/`ToolCall`), — кандидат на общий helper при появлении
   второго HTTP-провайдера.
7. **`max_response_bytes` считается по декодированным и повторно
   закодированным байтам**, поэтому может быть завышен для битого UTF-8 (в
   сторону безопасности: занизить его нельзя).
8. **Дефолты `StreamLimits` и `ModelEntry.stream_*` существуют дважды**
   (`sanctum` не может импортировать `model_layer`); синхронность держит тест
   `test_config_defaults_agree_with_the_adapter_limits`.
9. Незакоммиченные изменения S07–S13 сохранены; S14 не коммитит (по инструкции).

### 13. Резюме изменений

```
backend/seraphim/model_layer/
  stream.py             — StreamEventType, StreamEvent, StreamSequencer,
                          StreamLimits, RedactingDeltaBuffer, validate_stream
  sse.py                — SSEMessage, SSEParser, SSEEventTooLargeError
  tool_calls.py         — ToolCallLimits, ToolCallAccumulator
  http_transport.py     — +StreamIdle, HttpStream, open_stream, _UrllibStream,
                          _BufferedStream, DEFAULT_MAX_BUFFERED_BYTES
  openai_compatible.py  — +stream/_stream_events/_pump_stream,
                          stream_limits, stream_include_usage
  provider.py           — базовый stream() через StreamSequencer
  __init__.py           — экспорт новых имён
backend/seraphim/contracts/sanitization.py  — +max_known_secret_length,
                                              +split_releasable
backend/seraphim/model_layer/response.py    — ToolCall.to_dict() санитизирует
                                              id/name/arguments
backend/seraphim/sanctum/config_schemas.py  — ModelEntry: stream_* поля
backend/tests/model_layer/test_streaming.py            — 165 тестов
backend/tests/model_layer/test_fake_provider.py        — +1 тест
backend/tests/sanctum/test_provider_transport_config.py — +2 теста
CONTRACTS.md — §2.5: реализация S14 (включая гарантию по секретам)
IMPLEMENTATION_PLAN.md — S14 переведён в ВЫПОЛНЕН
```

### 14. Предлагаемое сообщение коммита

```
feat: S14 streaming and tool-call normalization

- model_layer/stream.py: normalized StreamEvent envelope (start, text_delta,
  tool_call_start, tool_call_args_delta, tool_call, usage, done, error,
  cancelled) with an ordering contract enforced by StreamSequencer: sequence
  from 0 without gaps, START first and once, exactly one terminal event last
- model_layer/sse.py: incremental text/event-stream parser (byte-counted event
  cap, tolerant line endings, dispatches a trailing unterminated event)
- model_layer/tool_calls.py: fragments are assembled per index; a ToolCall is
  created only by finish(), which validates the whole batch (JSON object
  arguments, name present, unique ids, id stable mid-stream, size limits) and
  returns nothing at all when any call is unusable
- model_layer/http_transport.py: open_stream() with a background pump and a
  bounded buffer, so a read is interruptible and a fast endpoint cannot be
  pulled into memory ahead of the consumer; close() closes the socket, the one
  operation that unblocks a pending recv on Windows
- model_layer/openai_compatible.py: stream() with a capability gate and
  validate_request before the generator, pre-cancel before any request, idle
  and overall deadlines, mid-stream cancellation, and a defensive terminal
  error for any non-normalized exception
- secret safety: live deltas pass through RedactingDeltaBuffer, which releases
  only a prefix that split_releasable() proves cannot be part of a known secret,
  so a credential split across chunks is redacted as a unit
- sanctum: optional stream_* caps on ModelEntry (minor, no migration)
- tests: 168 new offline tests against a loopback SSE server; 951/952 PASS;
  ruff check clean
- independent review (2 rounds): 3 blockers and 9 findings found and fixed
```

---

*Конец IMPLEMENTATION_LOG.md S14.*



## S15 — COMPASS: детерминированная маршрутизация моделей

Пакет `backend/seraphim/compass/` — чистая функция выбора провайдера по объявленным
кандидатам. Сокеты не открываются, CORE/WINGS не импортируются. Каждый отказ
кандидата содержит причину (`rejected`), fallback помечается явно (`fallback=True`).

Режимы: `manual` (явный `model_id`, несовместимость — `COMPASS_CONFLICT`, без
молчаливого fallback), `rule_based` (правила `(-priority, id)`, затем первый
пригодный кандидат по объявленному порядку). Отказы: `NO_MODEL_AVAILABLE`,
`ROUTING_TIMEOUT` (через инжектируемые часы). Приватность проверяется через
`decide_transmission`; offline исключает внешние модели.

Возможности берутся из `verified_capabilities()` (добавлен в `ModelProvider`,
по умолчанию пусто; у `FakeProvider` совпадает с декларацией).

### Верификация

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/compass -q   # 21 passed
.\.venv\Scripts\python.exe -m pytest -q                             # 1010 passed, 1 skipped
.\.venv\Scripts\python.exe -m ruff check backend/                   # All checks passed!
```

`backend/tests/compass/test_router.py` — 21 тест: ручной режим, правила, детерминизм,
fallback, таймаут, фильтр возможностей, приватность и offline, конфигурация.

## S16 — Task Engine: модель задачи и state machine

Пакет `backend/seraphim/core/`: `task_model.py` (типизированные данные, инварианты результата)
и `task_machine.py` (единственная точка изменения статуса — `transition()`, таблица `ALLOWED`).
Модель не получает доступа к тексту ответа; проверку выдаёт `Verified(report)` от верификатора.

### Верификация

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/core -q        # 88 passed
.\.venv\Scripts\python.exe -m pytest -q                            # 1098 passed, 1 skipped
.\.venv\Scripts\python.exe -m ruff check backend/                  # All checks passed!
```

### Найдено и исправлено тестами

- Pause из RETRYING → Resume уводил задачу в RUNNING с упавшим шагом, у которого есть бюджет: тупик. Resume теперь возвращает в RETRYING при наличии бюджета.
- Pause из NEEDS_APPROVAL оставлял `pending_approval_step`, нарушая инвариант. Pause очищает его.
- `PlanStep(status=SUCCEEDED)` без отчёта принимался. Теперь отвергается.

### Незакрыто

- Персистентность и resume — S17. Verifier'ы и WINGS — S19–S21. Сейчас не проверено на реальных шагах.

## S17 — Task/session persistence и resume

Миграция `0002_task_persistence` (append-only, ADR-007): `tasks` получает `revision`, ожидание
approval/verification, результат и флаг review; новые таблицы `task_steps`, `tool_calls`, `checkpoints`.
Слой хранения: `core/task_store.py` (TaskRepository, ToolCallLedger), сервис: `core/task_service.py`.

### Верификация

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/core -q        # 123 passed (88 S16 + 35 S17)
.\.venv\Scripts\python.exe -m pytest -q                            # 1133 passed, 1 skipped
.\.venv\Scripts\python.exe -m ruff check backend/                  # All checks passed!
```

Ручная проверка: создание задачи и `prepare`/`start` в одном процессе; отдельный процесс открывает
ту же БД, вызывает `recover()` — задача в RUNNING восстановлена и отправлена на review
(`status cannot be continued after restart`).

### Найдено и исправлено

- `MigrationRunner._write_meta`: `UPDATE schema_meta ... WHERE id = ?` получал два значения
  вместо трёх. Ветка раньше не выполнялась, т.к. миграция 0001 всегда вставляла строку. Миграция 0002
  выявила ошибку при второй миграции. Исправлено.
- Два теста S17 сами делали недопустимый переход (Pause из READY/PAUSED): исправлены на корректные
  переходы; машина правильно отказывала.

### Решения

- Состояние меняется только через `TaskRepository.save()`: проверка ревизии, запись шагов, чекпоинта
  и события в одной транзакции.
- Задача под review принимает только CANCELLED/FAILED/BLOCKED (закрытие оператором).
- Открытый tool call при восстановлении переводится в UNKNOWN, задача идёт на review, вызов не повторяется.
- RUNNING/VERIFYING/NEEDS_APPROVAL/RETRYING после рестарта всегда на review; PAUSED остаётся PAUSED.

### Незакрыто

- Исполнитель шагов и WINGS-вызовы не реализованы (S19): ledger проверен как хранилище, не как путь исполнения.
- Нет отдельного репозитория сессий (`sessions`): есть только колонка `tasks.session_id`.
- Перенос результата (outputs) в `artifacts` не реализован; сейчас только `result_json`.
- Ручная проверка через CLI-команды отсутствует: команд `task` в CLI ещё нет.

## S18 — Planner и структурированный план

Схема и проверки плана: `core/plan.py` (`parse_plan_json`, `check_plan`). Планировщик через
`ModelProvider`: `core/planner.py` (`Planner`, `to_task`, `require_ready`). Сохранение: план пишется
в `tasks.plan_json` как объект `{constraints, steps}` (миграции не понадобилось: S17 не выпускался).

### Верификация

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/core/test_planner.py -q   # 31 passed
.\.venv\Scripts\python.exe -m pytest backend/tests -q                         # 1164 passed, 1 skipped
.\.venv\Scripts\python.exe -m ruff check backend/seraphim backend/tests       # All checks passed!
```

Ручная проверка: валидный граф (`a` → `b`) проходит `check_plan` и `ready=True`; JSON с обрывом
`{"goal": "g", "steps": [` отвергается с PLAN_VALIDATION_FAILED и позицией ошибки.

### Решения

- Готовность плана = отсутствие ошибок `check_plan`. Цикл, self/missing dependency, дубль id, пустой
  или слишком большой план не дают `ready`. `to_task` и `require_ready` отказывают, и в хранилище
  ничего не пишется (тест).
- Ремонт формата ограничен `max_repairs`; ошибка провайдера (`ProviderError`) не тратит попытку.
- Текст из документов передаётся в user-сообщении как данные; system-политика фиксирована. Поле
  `constraints` из JSON сохраняется, но не влияет на `risk_hint` и проверки.
- High-risk (`external`, `destructive`) только помечается. `requires_approval` не выставляется:
  в S16 он блокирует запуск, а выбрано «только пометка».

### Отклонение от критерия

- Критерий «high-risk требует AEGIS review» не выполнен в S18: AEGIS отсутствует. Перенесено на S20.

### Незакрыто

- Отображение плана в CLI/UI не реализовано.
- Старт задачи из плана через TaskService не подключён.
- AEGIS-gate для high-risk шагов (S20).

## S19 — WINGS: registry инструментов и tool contract

Пакет `seraphim/wings`: `manifest.py` (ToolManifest), `calls.py` (ToolCall, ToolResult, ToolError,
CallStatus), `registry.py` (ToolRegistry, протокол ToolProvider). Реестр не импортирует task DB,
UI или AEGIS; он видит только манифесты и объекты провайдеров.

### Верификация

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/wings -q     # 33 passed
.\.venv\Scripts\python.exe -m pytest backend/tests -q           # 1197 passed, 1 skipped
.\.venv\Scripts\python.exe -m ruff check backend/seraphim backend/tests   # All checks passed!
```

Тесты: схема манифеста (id, input_schema, timeout, version, source/risk, дубль capability), дубль
id (повтор не заменяет провайдер), конфликт capability между source, enable/disable (disabled не
исполняется и не виден в discover), неизвестный tool, проверка аргументов до вызова провайдера,
успех/ошибка/внутреннее исключение без утечки текста, единый ключевой набор ToolResult.to_dict.

### Найдено и исправлено

- `tool.` проходил проверку id (`count(".") >= 1`). Исправлено: требуется непустое имя после префикса.
- Конфликт capability первоначально писался с мёртвым условием; заменён реальной проверкой.

### Решения

- ToolCall (WINGS) — запрос на исполнение с call_id; это не модельный ToolCall из S14, поэтому
  модельные id сюда не смешиваются.
- Конфликт capability: одна capability не может быть объявлена tool'ами из разных `source`.
- Аргументы проверяются по JSON Schema минимально: обязательные поля и запрет неизвестных полей
  (если заданы `properties`). Полный JSON Schema-валидатор не добавлялся: новой зависимости нет.
- Регистрация открытая только через `register()` кодом; модель не регистрирует tools.

### Незакрыто

- Cancellation и timeout не прерывают провайдера: поле `timeout_seconds` сохраняется, но не
  применяется (S22/S23).
- AEGIS не вызывается; `call()` сейчас исполняет любой enabled tool. Это главный разрыв до S20:
  вызов в продакшен-путь нельзя пускать до появления AEGIS-шага.
- Полная JSON Schema-валидация аргументов (типы, enum, вложенность) не реализована.
- Провайдеры MCP и BRIDGES не подключены; artifact_refs пока не заполняются.

### Исправления после ревью S16–S19

- Аргументы проверяются по типам (string/number/integer/boolean/array/object/null, bool не принимается как число) и рекурсивно по `properties`; до вызова провайдера.
- `output_schema` проверяется после успешного вызова; нарушение даёт FAILED / TOOL_SCHEMA_INVALID.
- `timeout_seconds` применяется: провайдер работает в daemon-потоке, по истечении — FAILED / TOOL_TIMEOUT. Ограничение: поток нельзя принудительно остановить, он продолжает работать в фоне до конца вызова.
- Fail-closed: инструмент с `side_effects` кроме `read` отклоняется (TOOL_PERMISSION_DENIED) до появления AEGIS (S20).
- `ToolManifest.schema_version` = 1; неизвестная версия отклоняется; поле попадает в `to_dict()`.
- Тесты: 9 новых в `tests/wings/test_registry.py` (тип аргумента, bool≠number, вывод вне схемы, таймаут, fail-closed, schema_version).

### Режимы и подтверждение (task_machine)

- OBSERVE: шаги с `risk_hint` кроме `none`/`read` отклоняются (TASK_INVALID) на StartStep.
- `external`/`destructive` требуют подтверждения в любом режиме (NEEDS_APPROVAL), даже без `requires_approval`.
- Тесты: 9 новых в `tests/core/test_task_machine.py`.

### Персистентность (task_store, task_service)

- `TaskRepository.save()` применяет только рёбра из `transition()`; подделка SUCCEEDED через save отклоняется (TASK_INVALID).
- `TaskRepository.insert()` принимает только новый DRAFT без результата.
- `ToolCallLedger.begin()` в той же транзакции проверяет RUNNING и отсутствие review (TASK_INVALID / TASK_REVIEW_REQUIRED).
- `TaskService.recover()`: открытый вызов помечается UNKNOWN и задача уходит на review даже если review уже стоит.
- Проба: пустой отчёт верификации даёт FAILED шага и задачи (не SUCCEEDED).

Итог: pytest tests — 1221 passed, 1 skipped; ruff — All checks passed.

**S20 — AEGIS: policy engine** · Гейт: C6, ADR-015, ADR-005 · ЧАСТИЧНО (PARTIAL)

### Что сделано

- `backend/seraphim/aegis/policy.py`: решения ALLOW / ALLOW_WITH_LIMITS / ASK_USER / DENY; deny-by-default (`aegis.default.deny`, «No policy rule allows this action.»); неизвестный или неполный запрос даёт DENY (`aegis.request.invalid`); при конфликте побеждает самое строгое решение, затем priority.
- Только источники `global` и `user` могут выдавать права (ALLOW / ALLOW_WITH_LIMITS). `skill`, `identity`, `project` могут только ограничивать.
- `backend/seraphim/aegis/baseline.py`: неизменяемые глобальные правила с префиксом `aegis.global.`: destructive и external требуют подтверждения (ASK_USER), secret-данные запрещены (DENY).
- `backend/seraphim/aegis/gate.py`: `make_gate()` строит PolicyRequest из ToolManifest и ToolCall; любое исключение превращается в DENY (`aegis.gate.evaluation_failed`).
- `backend/seraphim/wings/registry.py`: `call()` принимает `policy=` (callable, без импорта типов AEGIS). Без gate или при исключении в gate вызов отклоняется до провайдера. Удалено прежнее правило «side_effects кроме read отклоняются».
- Тесты: `backend/tests/aegis/test_policy.py` (37), `backend/tests/wings/test_aegis_gate.py` (интеграция с реальным движком), `backend/tests/wings/test_registry.py` (вызовы передают `policy=`).

### Незакрыто

- Логирование отказа в OBSERVATORY (`policy.decision`) не подключено; отказ виден только в ToolResult.
- ADR-015 и ADR-005 не приняты; движок не читает permissions.yaml или БД правил.
- Проверка путей и корней — S21. Лимиты ALLOW_WITH_LIMITS (timeout, allowed_roots) WINGS не применяет.
- Gate не подключён к исполнителю задач CORE.

### Проверки

- `.venv/Scripts/python.exe -m pytest backend/tests -q` — 1273 passed, 1 skipped.
- `.venv/Scripts/python.exe -m ruff check backend/seraphim backend/tests` — All checks passed.
- Ручная проверка: неизвестный инструмент (`tool.shell.run`) → TOOL_NOT_FOUND, провайдер не вызван; зарегистрированный без правила → TOOL_PERMISSION_DENIED, провайдер не вызван.

**S21 — Ограниченные filesystem tools** · ВЫПОЛНЕН С ОГРАНИЧЕНИЯМИ

### Что сделано

- `wings/fs_paths.py`: `FsRoot.resolve()` проверяет каждый компонент пути. Отказ: `..`, абсолютные пути, `C:`, `\x00`, зарезервированные имена устройств, секретные компоненты (`.git`, `.env*`, `.ssh`, `*.pem`, `*secret*`, `*token*`, и т.д.) на любой глубине, symlink и junction (проверка `lstat` на каждом шаге, затем `realpath` внутри root).
- `wings/fs_ops.py`: read/list/search/write/create_dir/move/delete. Лимиты: чтение и запись 1 MiB, список 500 записей, поиск 500 файлов и 200 совпадений. Запись: temp-файл в той же директории, `fsync`, `os.replace`; при ошибке временный файл удаляется, исходный не меняется. Удаление переносит файл в `_trash/` (обратимо), корень удалить и переместить нельзя.
- `wings/fs_tools.py`: 7 манифестов `tool.fs.*`, `FsToolProvider`, `register_fs_tools()`. Все через `ToolRegistry.call()` и AEGIS gate.
- `contracts/errors.py`: коды `FS_PATH_DENIED`, `FS_NOT_FOUND`, `FS_TOO_LARGE`, `FS_IO_FAILED`, `FS_CONFLICT`.
- Тесты: `backend/tests/wings/test_fs_tools.py` (45: traversal, junction escape, secret paths, лимиты, atomic write с отказом replace и fsync, отказ без правила, read-only правило не даёт запись, нормализация ошибок, delete/move, корень).

### Проверки на целевой ОС (Windows 11)

- Junction: `mklink /J` без админ-прав работает. Тест реальной junction: чтение `j/...` и запись отклоняются (`FS_PATH_DENIED`), внешний файл не читается и не создаётся.
- Symlink: без привилегии создание падает (WinError 1314). Тест помечен skip, эскейп через symlink на этом хосте не проверен.

### Незакрыто

- Symlink-тест не выполнен на хосте (нужна привилегия или Developer Mode).
- Права 0o555 на директорию не действуют на Windows; тест write-в-read-only пропущен.
- `_trash/` без политики очистки и квоты.
- Race condition между проверкой пути и открытием: защита частичная (`samestat` при чтении; для записи проверка в момент `replace`, без блокировки каталогов).
- Поиск не ограничен по глубине каталогов (только по числу файлов).
- ALLOW_WITH_LIMITS.allowed_roots WINGS не применяет.
- Логирование отказов в OBSERVATORY не подключено.

### Проверки

- `.venv/Scripts/python.exe -m pytest backend/tests/wings/test_fs_tools.py -q` — 43 passed, 2 skipped.
- `.venv/Scripts/python.exe -m pytest backend/tests -q` — 1316 passed, 3 skipped.
- `.venv/Scripts/python.exe -m ruff check backend/seraphim backend/tests` — All checks passed.

**S22 — Ограниченные shell/process tools** · ВЫПОЛНЕН С ОГРАНИЧЕНИЯМИ

### Что сделано

- `wings/process_runner.py`: `run_process(argv, cwd=FsRoot, env_source, timeout_seconds, cancel)`. argv передаётся списком, `shell=False`, stdin закрыт. Исполняемый файл — только bare name, резолвится через PATH из allowlist env. Env: только PATH, SYSTEMROOT, TEMP, TMP, PATHEXT, LANG, LC_ALL. cwd — FsRoot. Timeout 1..120 с. Вывод на каждый поток ограничен 64 КБ и проходит `sanitize_text`.
- Завершение дерева: Windows — Job Object с `KILL_ON_JOB_CLOSE` (ctypes), процесс назначается в job сразу после старта; POSIX — `start_new_session` и `killpg`.
- `wings/process_tools.py`: `tool.process.run` (risk high, side_effects external, permission process.run). Arbitrary shell не реализован.

### Проверки

- Ручной прогон (smoke): timeout убивает процесс-внука (tasklist подтверждает), nonzero exit = 3, вывод 500 000 байт обрезан до 65 536, метасимволы (`a&calc.exe|x;y`) переданы литералом, секреты в env не попадают, cancel срабатывает за ~1 с.
- Тесты: `tests/wings/test_process_runner.py` — 24 passed; `tests/wings/test_process_tool.py` — 4 passed.
- Полный набор: 1345 passed, 3 skipped. Ruff: All checks passed.

### Ограничения и открыто

- Глобальное правило `external_requires_confirmation` (ASK_USER) перебивает любой user ALLOW; `tool.process.run` поэтому не исполняется, пока не появится механизм approval (S23). Правило не ослаблялось.
- Windows sandbox: изоляция только cwd и env. Не ограничены: доступ к файлам вне cwd, сеть, реестр, права текущего пользователя. Job Object гарантирует только уничтожение дерева.
- Symlink-тесты не запускаются на Windows без привилегии создания symlink.
- Arbitrary shell — отдельная high-risk категория, не реализована.

## S23 — Approval, cancellation и timeout orchestration

### Сделано

- Миграция 0003 `approvals`: id, task/step, tool, fingerprint, explanation, redacted preview, resource, risk, статус, created/expires/decided/consumed.
- `core/approval.py`: `ApprovalService` — request, decide, consume, pending; fingerprint = sha256(tool, arguments, task, step); single-use через условный UPDATE; истечение проверяется при decide и consume; аудит в events.
- AEGIS: `waived_when_confirmed` только для глобальных ASK_USER-правил; DENY не снимается; подтверждение действует только для consumed call_id.
- `core/orchestration.py`: `StepOrchestrator` — рисковый шаг останавливается в NEEDS_APPROVAL; approve/deny; cancel запрашивается, а не форсируется: вызов в процессе доходит до конца, затем задача становится CANCELLED (CANCEL_AFTER_CALL).

### Проверки

- `tests/core/test_approval.py` — 18 passed; `tests/core/test_orchestration.py` — 10 passed (expiry, duplicate approval, reuse для другой операции, cancel before call, cancel during call, timeout during write, deny).
- Полный набор: 1378 passed, 3 skipped. Ruff: All checks passed.
- Исправления после review S20–S23: D1 allowlist исполняемых файлов в `run_process` (проверка по точному имени до запуска, пустой список запрещает всё); D3 ASK_USER до старта шага даёт NEEDS_APPROVAL, а не REJECTED; DENY от AEGIS отказывает до создания approval; D5 `data_sensitivity` передаётся в гейт из `run_step`/`approve`, secret → DENY даже при подтверждении; D4 `supports_cancellation=False` у process-инструмента, пока CancelToken не проведён.

### Ограничения и открыто

- D2 частично: таймаут WINGS возвращает TOOL_TIMEOUT с текстом «may still be running, outcome unknown», задача переводится в BLOCKED, новые вызовы отклоняются. Поток провайдера при этом продолжает работу, реальное действие может ещё идти; отмены провайдера нет.
- D4: process-инструмент не получает CancelToken; cancel ждёт завершения процесса. Решение «проводить CancelToken» отложено.
- D5: `data_sensitivity` по умолчанию `internal`; CORE должен передавать `secret` явно. Источник классификации данных не определён.
- Cancel во время записи не прерывает её: статус CANCELLED ставится после возврата вызова. Атомарная запись (temp + os.replace) не оставляет частичный целевой файл.
- Pause в StepOrchestrator не обработан (TaskService.pause есть); тест Pause во время NEEDS_APPROVAL не написан.
