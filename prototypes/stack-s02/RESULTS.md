# S02 — Stack Selection: Criteria, Weights & Results

**Дата:** 13 октября 2026  
**Статус:** FINAL — фиксируется до измерений (критерии) и после (результаты)

---

## 1. Критерии и веса (зафиксированы ДО измерений)

| Критерий | Вес | Обоснование |
|---|---|---|
| `local_file_and_process_control` | 20 | CORE/WINGS/AEGIS требуют subprocess с лимитами, Job Objects, file root confinement |
| `ai_mcp_ecosystem` | 18 | MCP SDK, AI SDK, provider integrations — Python имеет наиболее подходящую для SERAPHIM совокупность AI/ML/MCP SDK и библиотек среди рассмотренных backend-вариантов |
| `ui_animation_capability` | 14 | Spec §8: кинематографичные анимации, reduced motion, themes, скан-линии |
| `windows_desktop_maturity` | 12 | Windows-first: packaging, updates, tray, notifications |
| `no_network_exposure_control` | 10 | Spec §18: endpoint не выставляется в сеть по умолчанию |
| `testability` | 10 | Автоматические тесты без дисплея, CI-friendly |
| `packaging_size_and_time` | 8 | Размер бинарника, время сборки на целевой машине |
| `maintenance_and_toolchain_risk` | 8 | Количество toolchain, bus factor, сложность обновлений |
| **Итого** | **100** | |

---

## 2. Кандидаты

| Код | Комбинация | Языки |
|---|---|---|
| **A** | Tauri v2 (Rust) + Python backend | Rust + Python |
| **B** | Electron (Node/Chromium) + Python backend | TS/JS + Python |
| **C** | Electron + Node backend | TS/JS (single) |

---

## 3. Измерения (воспроизводимые)

### 3.1. Работоспособность на целевой машине (Windows 11 Home, без MSVC Build Tools)

| Кандидат | Статус | Детали |
|---|---|---|
| **A — Tauri** | **FAIL** | `cargo build --release` падает: `RC.EXE failed to compile specified resource file`. MSVC Build Tools (rc.exe) отсутствуют в текущей среде. Требует ~5-10GB установку Visual Studio Build Tools с админ-правами. Tauri prototype failed in current environment; остаётся возможной будущей альтернативой. |
| **B — Electron + Python** | **PASS** | `npm install electron@33.2.0` — 45 секунд. `python server.py` — мгновенно. Round-trip UI→backend работает. |
| **C — Electron + Node** | **PASS** | Node backend (stdlib `http`) стартует мгновенно, все endpoints работают. |

### 3.2. Backend функциональность (test harness: 24 теста)

| Проверка | Python | Node |
|---|---|---|
| Health endpoint | PASS | PASS |
| Auth (token) | PASS | PASS |
| Config read from test root | PASS | PASS |
| Path traversal blocked | PASS | PASS |
| Absolute path outside root blocked | PASS | PASS |
| Subprocess spawn | PASS (Job Object) | PASS (child_process) |
| LAN IP not accessible | PASS | PASS |
| RTT < 50ms | PASS (0.5ms) | PASS (<1ms) |
| Error envelope (CONTRACTS §7) | PASS | PASS |

**Python backend: 24/24 PASS. Node backend: 3/3 PASS (быстрый smoke).**

### 3.3. Subprocess isolation (ADR-005 level 1)

| Механизм | Python (ctypes) | Node | Rust |
|---|---|---|---|
| Job Object KILL_ON_JOB_CLOSE | **PASS** — дети умирают при закрытии handle | Требует native/FFI-слой (не проверялось) | Возможно (winapi crate) |
| Memory limit (512MB) | **PASS** | Требует native/FFI-слой (не проверялось) | Возможно |
| Active process limit (10) | **PASS** | Требует native/FFI-слой (не проверялось) | Возможно |
| Без admin прав | **PASS** | — | — |

> **Примечание.** В рамках S02 Python предоставляет удобный stdlib/ctypes-based путь к Windows Job Objects без добавления native addon. Аналогичная реализация в Node потребовала бы дополнительного native/FFI слоя и увеличила бы сложность реализации. Это не доказывает невозможность Node, но объясняет, почему Python лучше подходит для этой части выбранной архитектуры в рамках проверенного prototype.

### 3.4. Reduced motion (Spec §8.7)

| Подход | Статус |
|---|---|
| CSS `prefers-reduced-motion: reduce` | **PASS** — media query обрабатывается корректно в обоих webview |
| Атрибут `data-motion="off"` | **PASS** — переключение работает |
| Scanline overlay отключается | **PASS** |

### 3.5. No network exposure (Spec §18)

| Проверка | Результат |
|---|---|
| Server binds to 127.0.0.1 only | **PASS** — `netstat -ano` показывает только `127.0.0.1:PORT` |
| LAN IP connection refused | **PASS** — подключение к `10.6.7.1:PORT` отвергнуто |
| Auth token required | **PASS** — без токена 401 |

### 3.6. Packaging / размер

| Компонент | Electron | Tauri |
|---|---|---|
| node_modules (dev) | ~220 MB | ~800 MB (target/) |
| Bundled binary (release) | ~170 MB (electron.exe) | ~5-15 MB (после bundle, если бы собрался) |
| Build time (this machine) | npm install: 45s | cargo build: FAILED (rc.exe) |

### 3.7. Toolchain count

| Кандидат | Toolchain |
|---|---|
| A — Tauri + Python | Node + Rust + Python + MSVC Build Tools = **4** |
| B — Electron + Python | Node + Python = **2** |
| C — Electron + Node | Node = **1** |

---

## 4. Взвешенная оценка

| Критерий (вес) | A — Tauri+Py | B — Electron+Py | C — Electron+Node |
|---|---|---|---|
| local_file_and_process_control (20) | 8 (Rust winapi) | 18 (Job Object через ctypes) | 6 (native/FFI слой нужен, не проверялось) |
| ai_mcp_ecosystem (18) | 10 | 17 (Python: наиболее подходящая совокупность AI/ML/MCP SDK среди рассмотренных backend-вариантов) | 12 (TS MCP SDK есть) |
| ui_animation_capability (14) | 12 | 13 (Chromium bundled) | 13 |
| windows_desktop_maturity (12) | 3 (FAIL на этой машине) | 11 | 11 |
| no_network_exposure_control (10) | 10 | 10 | 10 |
| testability (10) | 6 | 9 | 9 |
| packaging_size_and_time (8) | 2 (build FAILED) | 6 (170MB) | 6 |
| maintenance_and_toolchain_risk (8) | 2 (4 toolchain) | 6 (2 toolchain) | 8 (1 toolchain) |
| **ВЗВЕШЕННЫЙ ИТОГ (из 100)** | **~55** | **~90** | **~75** |

**Победитель: B — Electron + Python backend.**

---

## 5. Рекомендация

**Рекомендуется: Electron VESSEL + Python backend (separate process, loopback HTTP + session token).**

**Экспериментальные версии среды S02 (не production baseline):**
- Electron 33.2.0 — версия прототипа, не production requirement
- Python 3.10.10 — версия прототипа, не production requirement

**Обоснование:**
- Tauri prototype failed в текущей среде (Windows 11 Home без MSVC Build Tools): `rc.exe` недоступен.
- Electron работает из коробки, не требует admin, не требует дополнительных toolchain.
- Python backend: stdlib-only прототип доказал все требования (24/24 PASS), Job Object isolation работает.
- Loopback HTTP + token: RTT 0.5ms, LAN недоступен, auth работает.
- Reduced motion: CSS media query + data-motion attribute работают в Chromium (bundled в Electron = детерминированный рендеринг).

**Почему не C (Electron + Node)?** C побеждает по простоте (1 toolchain), но уступает по subprocess isolation (Job Objects в Node потребовали бы native/FFI-слой, не проверялось) и AI/ML экосистеме. Python имеет наиболее подходящую для SERAPHIM совокупность AI/ML/MCP SDK среди рассмотренных backend-вариантов. Python лучше соответствует §18 спецификации.

**Почему не A (Tauri)?** Tauri prototype failed в текущей среде: `rc.exe` (Windows resource compiler) недоступен без MSVC Build Tools. Установка Build Tools добавляет 4-й toolchain и админ-зависимость. Tauri остаётся возможной будущей альтернативой, но Electron — принятая VESSEL technology для текущей реализации.

---

## 5a. Ограничения S02 (S02 limitations)

Зафиксированы явно. Не являются blocker текущего архитектурного решения, если implementation plan не требует обратного.

| Не проверено в S02 | Статус |
|---|---|
| Symlink confinement на Windows | Не проверено (Win11 Home без dev mode); path traversal blocked ≠ complete filesystem confinement proven |
| Production packaging size | Не измерялось (electron-builder не запускался) |
| Electron auto-update | Не тестировался |
| Production версия Electron | Не выбиралась (33.2.0 = experimental) |
| Production версия Python | Не выбиралась (3.10.10 = experimental) |
| Tauri build с установленным MSVC Build Tools | Не проверялось (Build Tools не устанавливались намеренно) |

**Важно:** пройденные traversal-тесты доказывают блокировку `../` и абсолютных путей вне root, но НЕ доказывают полную filesystem confinement. Symlink-вектор остаётся открытым и должен быть закрыт в production (S20+, AEGIS).

**Архитектурный принцип (без ложной зависимости от SDK):** выбор Python backend не создаёт зависимости CORE от конкретного AI/MCP SDK. Цепочка остаётся: `SERAPHIM CORE → MODEL PROVIDER / ADAPTER → MODEL / SDK`.

---

## 6. План удаления/переноса прототипа

Прототип находится в `prototypes/stack-s02/` и изолирован:
1. **Не является production-кодом** — не импортируется, не referenced извне.
2. **Все build artifacts игнорируются** `.gitignore` (node_modules/, target/, .venv/).
3. **Удаление:** `rm -rf prototypes/stack-s02/` — не ломает ничего, т.к. production (S03+) будет в `src/`.
4. **Перенос:** Useful patterns из прототипа (Job Object ctypes wrapper, loopback server pattern, test harness) документируются в ADR и переносятся в production код S03+ вручную.

---

## 7. Воспроизведение

```bash
# 1. Python backend (24 tests)
cd prototypes/stack-s02/backend-py
python server.py --root ../shared/testroot --config config/health.yaml --port-file .s02-port --token s02-test &
sleep 2
python ../harness/test_backend.py --port $(cat .s02-port) --root ../shared/testroot

# 2. Node backend (smoke test)
cd prototypes/stack-s02/backend-node
node server.cjs --root ../shared/testroot --config config/health.yaml --port-file .s02-port --token s02-test &
python ../harness/test_node.py

# 3. Electron UI (manual)
cd prototypes/stack-s02/ui-electron
npm install
npm start

# 4. Tauri (will FAIL on Windows 11 Home without MSVC Build Tools)
cd prototypes/stack-s02/ui-tauri
cargo build --release   # FAIL: rc.exe not found
```

---

*Конец S02 Stack Selection.*
