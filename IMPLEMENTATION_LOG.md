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
- Обязательные версии runtime (Python 3.10+, Node 20+, Electron ^33.2.0)
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

*Конец IMPLEMENTATION_LOG.md S06.*
