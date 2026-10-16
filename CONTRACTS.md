# SERAPHIM — Архитектурный контракт (S01)

**Версия контракта:** 0.1  
**Дата:** 13 октября 2026  
**Статус:** PROPOSED — ожидает подтверждения на C1  
**Источник истины:** `SERAPHIM_Full_Architecture_Spec.md` v0.1, разделы 0–27  
**Связанные документы:** `ARCHITECTURE_DECISIONS.md`, `IMPLEMENTATION_PLAN.md`

---

## 0. Правила чтения

- Каждый модуль описан как: **ответственность** / **входы** / **выходы** / **запретные обязанности**.
- Слои нумеруются от 0 (базовые типы) до 13 (экспериментальная зона). Зависимость только вниз по номеру слоя или через интерфейс из слоя 0.
- Слой 0 (CONTRACTS) — это не подсистема, а набор общих типов, интерфейсов, кодов ошибок и форматов событий. Он не имеет собственной бизнес-логики и не зависит ни от чего.
- Конфликтующие требования спецификации вынесены в §11 с предлагаемым разрешением и пометкой статуса.
- Открытые вопросы — в §12.
- Секреты не включены в контракт; они упоминаются как граница (TB-7).

---

## 1. Единый словарь (22 подсистемы)

| № | Название | Ответственность (кратко) |
|---|---|---|
| 1 | **CORE** | Runtime, координация, жизненный цикл задач |
| 2 | **SANCTUM** | Идентичность, конфигурация, системные инструкции, профиль |
| 3 | **AEGIS** | Политики безопасности, права, изоляция, approvals |
| 4 | **COMPASS** | Маршрутизация моделей, агентов, Skills и способов исполнения |
| 5 | **MODEL LAYER** | Провайдеры и модели (chat, streaming, tool calls, vision) |
| 6 | **MEMORY** | Контекст, проектная память, session memory, retrieval |
| 7 | **ARCHIVE** | Долговременная история, завершённые задачи, артефакты, handoff |
| 8 | **EXPERIENCE** | Извлечение наблюдений о том, что сработало или нет |
| 9 | **INSTINCTS** | Кандидаты на повторно используемые эвристики |
| 10 | **WINGS** | Общий слой инструментов и их оркестрации |
| 11 | **BRIDGES** | Интеграции с приложениями: discovery, SDK, adapter, tests |
| 12 | **MCP GATEWAY** | Подключение и экспорт MCP tools/resources/prompts |
| 13 | **EYES** | Скриншоты, изображения, визуальное наблюдение и проверка |
| 14 | **VOICE** | Чат, голосовой ввод/вывод и диалоговый интерфейс |
| 15 | **FORGE** | Создание, изменение, версионирование артефактов |
| 16 | **SKILLS** | Процедурное знание и workflow-пакеты |
| 17 | **LABORATORY / LAB** | Бенчмарки, оценки моделей, Skills и интеграций |
| 18 | **OBSERVATORY** | События, журналы, метрики, диагностика |
| 19 | **PULSE** | Здоровье компонентов, фоновые процессы, уведомления |
| 20 | **VESSEL** | Desktop-оболочка и рабочий интерфейс |
| 21 | **REGISTRY** | Реестр проектов, моделей, Skills, интеграций и компонентов |
| 22 | **APOCRYPHA** | Изолированная экспериментальная зона |

---

## 2. Паспорта подсистем

### 2.1. CORE — агентный runtime

| Поле | Значение |
|---|---|
| **Ответственность** | Создание задач, управление lifecycle (DRAFT→READY→RUNNING→VERIFYING→SUCCEEDED/CANCELLED/FAILED/BLOCKED), планирование, executor loop, recovery, anti-loop, checkpoints, verification coordination, postcondition checking |
| **Входы** | Цель пользователя (из VOICE/VESSEL/CLI); предложение модели от MODEL LAYER через COMPASS; решения AEGIS; результаты WINGS; данные из MEMORY/ARCHIVE |
| **Выходы** | Структурированный план (task_steps, dependencies); сохранённый task state; verification report со статусами (выполнено/проверено/частично проверено/не проверено); events в OBSERVATORY; артефакты через FORGE |
| **Запретные обязанности** | Не реализует частные API приложений; не вызывает инструменты напрямую — только через WINGS; не выдаёт себе разрешения; не владеет MEMORY (координирует retrieval, но Task State — владение CORE, а storage — MEMORY); не хранит конфигурацию; не принимает решения о маршрутизации моделей (COMPASS); не управляет файловой системой напрямую |
| **Владелец состояния задачи** | CORE (Task State — единственный источник истины о статусе) |
| **События** | task.created, task.started, task.completed, step.started, step.failed, task.cancelled, task.paused, task.blocked, verification.result |
| **Ошибки** | CONTRACT_VERSION_UNSUPPORTED, TASK_INVALID, PLAN_VALIDATION_FAILED, RECOVERY_MAX_ATTEMPTS, ANTI_LOOP_DETECTED, VERIFY_TIMEOUT |

### 2.2. SANCTUM — идентичность и конфигурация

| Поле | Значение |
|---|---|
| **Ответственность** | Загрузка и валидация пользовательской конфигурации (YAML/JSON/MD); identity (personality.md, system_prompt.md, response_style.md, user_preferences.md); управление секретами (API keys, токены); тема, локализация, пути, privacy policy; приоритет настроек |
| **Входы** | Файлы из `config/`, `identity/`; команды CLI (seraphim config); GUI-настройки (через VESSEL→CORE API) |
| **Выходы** | Нормализованный конфигурационный объект (read-only snapshot); валидированная identity; секреты в защищённом хранилище; schema-валидированные данные |
| **Запретные обязанности** | Не управляет задачами; не выполняет действия на внешних системах; не изменяет политику AEGIS; не хранит динамическое состояние задач; не хранит секреты в открытом тексте |
| **Владелец состояния** | SANCTUM владеет конфигурационным объектом и identity; файл `config/` + `identity/` — источник истины; значения секретов — платформенное хранилище (S09) |
| **События** | config.loaded, config.changed, config.validation_failed, identity.loaded, secret.accessed |
| **Ошибки** | CONFIG_FILE_NOT_FOUND, CONFIG_SCHEMA_INVALID, SECRET_ACCESS_DENIED, SECRET_NOT_FOUND, SECRET_REF_INVALID, SECRET_STORE_UNAVAILABLE, CONFIG_CONFLICT_DETECTED |

### 2.3. AEGIS — безопасность и разрешения

| Поле | Значение |
|---|---|
| **Ответственность** | Независимый policy engine; принятие решений ALLOW/DENY/ASK_USER/ALLOW_WITH_LIMITS перед каждым действием; классификация операций (чтение/запись/удаление файлов, shell, сеть, браузер, GUI, секреты, внешние MCP, публикация данных); изоляция неизвестных адаптеров; режим audit-only; редактирование чувствительных данных перед передачей модели; проверка prompt injection в недоверенных данных |
| **Входы** | Запрос на действие от CORE/WINGS; контекст действия (tool ID, аргументы, цель); политика из SANCTUM; данные из недоверенных источников |
| **Выходы** | Решение policy (ALLOW/DENY/ASK_USER/ALLOW_WITH_LIMITS); лимиты (тайм-аут, CPU, память); редакция чувствительных полей; events в OBSERVATORY |
| **Запретные обязанности** | Не выполняет действия; не маршрутизирует модели; не хранит историю задач; не изменяет свою политику через недоверенные данные; не позволяет Skill менять системные политики |
| **События** | policy.decision, policy.audit_mode, injection_detected, permission_denied |
| **Ошибки** | POLICY_EVALUATION_FAILED, UNTRUSTED_DATA_DETECTED, INSUFFICIENT_PERMISSIONS |

### 2.4. COMPASS — маршрутизация

| Поле | Значение |
|---|---|
| **Ответственность** | Выбор подходящей модели, роли агента, Skill и способа исполнения; учёт типа задачи, качества на похожих задачах, context window, tool calling, задержка, стоимость, доступность, privacy, offline-режим; объяснимый выбор (rule_based + manual, future adaptive); проверка доступности модели через MODEL LAYER health check |
| **Входы** | Тип задачи, контекст задачи, требования (vision, tool calls, context size), доступные модели, политика privacy |
| **Выходы** | Выбранная модель/роль/Skill с объяснением; fallback-протокол |
| **Запретные обязанности** | Не меняет права AEGIS; не выполняет вызовы моделей; не хранит историю маршрутизации; не обучается автоматически (до Phase 12) |
| **События** | model.selected, routing.failed, fallback.applied |
| **Ошибки** | NO_MODEL_AVAILABLE, ROUTING_TIMEOUT, COMPASS_CONFLICT |

### 2.5. MODEL LAYER — провайдеры и модели

| Поле | Значение |
|---|---|
| **Ответственность** | Абстракция провайдеров (облачные, OpenAI-compatible, локальные); chat, streaming, tool calls, vision, JSON schema; health check; metadata провайдера (context limit, ограничения); аутентификация; передача данных наружу определяется privacy policy |
| **Входы** | Модельный запрос от CORE/COMPASS; конфигурация из SANCTUM |
| **Выходы** | Сгенерированный ответ (текст, tool calls, vision); health status; метрики (токены, стоимость, время) |
| **Запретные обязанности** | Не принимает решения о маршрутизации (COMPASS); не вызывает инструменты; не хранит историю задач; не предполагает, что endpoint реализует полный OpenAI-compatible API |
| **События** | provider.health_changed, provider.response, provider.error, token_usage.reported |
| **Ошибки** | PROVIDER_UNAVAILABLE, PROVIDER_AUTH_FAILED, PROVIDER_TIMEOUT, RESPONSE_FORMAT_INVALID |

### 2.6. MEMORY — контекст и память

| Поле | Значение |
|---|---|
| **Ответственность** | Слои памяти: User Memory, Project Memory, Session Memory; retrieval (поиск, FTS, семантический, reranking); context pack; provenance (источник, дата, scope, уверенность); freshness и confidence; управление жизненным циклом записей |
| **Входы** | Запрос контекста от CORE; данные для записи от CORE/WINGS/EXPERIENCE; проектная информация |
| **Выходы** | Контекстный пакет (ограниченного размера); результаты поиска с источниками и релевантностью; подтверждённые/кандидатные записи |
| **Запретные обязанности** | Не владеет Task State (CORE); не принимает решения о маршрутизации; не выполняет действия; не управляет интеграциями |
| **Владелец состояния** | MEMORY владеет storage/retrieval API для memory-слоёв (User/Project/Session). Task State — CORE, не MEMORY. |
| **События** | memory.retrieval, memory.written, memory.stale, memory.forget |
| **Ошибки** | MEMORY_NOT_FOUND, RETRIEVAL_TIMEOUT, CONTEXT_OVERFLOW |

### 2.7. ARCHIVE — долговременная история

| Поле | Значение |
|---|---|
| **Ответственность** | Хранение завершённых задач, старых результатов, артефактов и handoff; долгосрочное хранение с минимальным доступом; export/import архивов |
| **Входы** | Завершённые задачи из CORE; артефакты из FORGE; handoff от MULTI-AGENT |
| **Выходы** | Доступ к архивным данным по ID/поиску; export архивов |
| **Запретные обязанности** | Не управляет текущими задачами; не выполняет действия; не участвует в маршрутизации |
| **События** | archived.task_saved, archive.exported, archive.imported |
| **Ошибки** | ARCHIVE_NOT_FOUND, ARCHIVE_IMPORT_FAILED |

### 2.8. EXPERIENCE — извлечение наблюдений

| Поле | Значение |
|---|---|
| **Ответственность** | Извлечение наблюдений о том, что сработало или нет; создание Experience candidate с provenance/confidence; передача в INSTINCTS при подтверждении |
| **Входы** | Результаты задач из CORE; события OBSERVATORY |
| **Выходы** | Experience candidate с confidence/provenance/scope; данные для INSTINCTS |
| **Запретные обязанности** | Не изменяет системные инструкции; не создаёт Skill напрямую; не изменяет глобальные политики |
| **События** | experience.candidate_created, experience.confirmed, experience.rejected |
| **Ошибки** | EXPERIENCE_CONTRADICTION, EXPERIENCE_INVALID_PROVENANCE |

### 2.9. INSTINCTS — эвристики

| Поле | Значение |
|---|---|
| **Ответственность** | Кандидаты на повторно используемые эвристики с confidence, provenance, scope, временем подтверждения и статусом; ручное подтверждение/отклонение |
| **Входы** | Experience candidate из EXPERIENCE; ручное подтверждение пользователя |
| **Выходы** | Принятая эвристика; Instinct candidate (candidate/accepted/stale/disputed/rejected) |
| **Запретные обязанности** | Не выполняет действия; не изменяет системные инструкции автоматически; не заменяет Skill |
| **События** | instinct.candidate_created, instinct.accepted, instinct.rejected, instinct.stale |
| **Ошибки** | INSTINCT_INVALID_SCOPE, INSTINCT_CONTRADICTION |

### 2.10. WINGS — инструменты

| Поле | Значение |
|---|---|
| **Ответственность** | Единый внутренний слой вызова инструментов; registry инструментов с contract (id, schema, permissions, risk, timeout, cancellation); валидация schema; нормализация вызовов и результатов; изоляция вызовов; execution with limits |
| **Входы** | Запрос действия от CORE (через AEGIS); зарегистрированный tool ID; tool provider interface |
| **Выходы** | Нормализованный результат; события в OBSERVATORY; результаты postcondition checks |
| **Запретные обязанности** | Не регистрирует инструменты напрямую через модельный ответ; не принимает решения о разрешениях (AEGIS); не владеет бизнес-логикой адаптеров (BRIDGES) |
| **События** | tool.call.started, tool.call.completed, tool.call.failed, tool.registered, tool.unregistered |
| **Ошибки** | TOOL_NOT_FOUND, TOOL_SCHEMA_INVALID, TOOL_TIMEOUT, TOOL_CANCELLED, TOOL_PERMISSION_DENIED |

### 2.11. BRIDGES — интеграции приложений

| Поле | Значение |
|---|---|
| **Ответственность** | Discovery приложений; Capability Mapper; Adapter SDK; Integration Manifest; Test Harness (connection, smoke, contract, regression, recovery); Package Manager (install/update/rollback/disable/uninstall); Compatibility Registry; Skill Composer (черновой Skill из проверенных процедур) |
| **Входы** | Выбранные приложения из Discovery; тестовые документы; manifest из SANCTUM |
| **Выходы** | Подключённые адаптеры с capabilities; test reports (PASS/FAIL/UNVERIFIED); Skill templates; capability IDs в WINGS Registry |
| **Запретные обязанности** | Не управляет задачами; не маршрутизирует модели; не меняет политику AEGIS; не генерирует произвольные драйверы (автоматическое reverse engineering GUI — поздняя фаза) |
| **События** | integration.discovered, integration.enabled, integration.health_changed, integration.test_failed |
| **Ошибки** | INTEGRATION_TIMEOUT, INTEGRATION_SCHEMA_MISMATCH, INTEGRATION_TEST_FAILED, INTEGRATION_COMPATIBILITY_ERROR |

### 2.12. MCP GATEWAY — шлюз MCP

| Поле | Значение |
|---|---|
| **Ответственность** | Подключение локальных/удалённых MCP-серверов; хранение разрешённых параметров запуска; обнаружение tools/resources/prompts; валидация схем; тайм-ауты; нормализация ошибок; журналирование; перезапуск серверов; опциональный экспорт внутренних инструментов SERAPHIM через MCP |
| **Входы** | Конфигурация MCP из SANCTUM (mcp.yaml); запросы от WINGS |
| **Выходы** | Нормализованные tools/resources/prompts в WINGS Registry; health status; diagnostics |
| **Запретные обязанности** | Не даёт внешнему MCP доступ к другим MCP, памяти или всему диску; не изменяет политику AEGIS; не регистрирует инструменты без валидации |
| **События** | mcp.connected, mcp.disconnected, mcp.health_changed, mcp.tool_discovered, mcp.connection_failed |
| **Ошибки** | MCP_CONNECTION_FAILED, MCP_INVALID_SCHEMA, MCP_TIMEOUT, MCP_UNTRUSTED |

### 2.13. EYES — визуальная подсистема

| Поле | Значение |
|---|---|
| **Ответственность** | Скриншоты рабочего стола, окон, браузера, CAD viewport, рендеры; сравнение состояний; передача изображений vision-модели; хранение визуальных доказательств; визуальные проверки до/после GUI действий; приоритет API/DOM над OCR |
| **Входы** | Запрос на скриншот/сравнение от CORE/WINGS/EYES; изображения от пользователя |
| **Выходы** | Визуальные артефакты с integrity hash; визуальные доказательства для verification; изображения для vision-моделей |
| **Запретные обязанности** | Не выводит точные технические свойства только из визуального впечатления (если проверяется через API); не управляет задачами; не хранит изображения без приватности-проверки |
| **События** | screenshot.taken, visual_comparison.completed, vision.requested |
| **Ошибки** | SCREENSHOT_FAILED, VISUAL_COMPARISON_FAILED, VISION_MODEL_ERROR |

### 2.14. VOICE — взаимодействие с пользователем

| Поле | Значение |
|---|---|
| **Ответственность** | Чат (MVP), текстовый ввод, план, подтверждения, события, вызовы инструментов, вложения, Pause/Resume/Cancel, ссылки на артефакты; голосовой ввод/вывод (future); hands-free (future); голосовая функция — необязательный канал, не отдельный мозг |
| **Входы** | Сообщения пользователя; UI-команды (Pause/Resume/Cancel) |
| **Выходы** | Нормализованные сообщения задачам в CORE; ответы пользователю через VESSEL |
| **Запретные обязанности** | Не управляет задачами напрямую; не выполняет действия; не хранит историю задач |
| **События** | message.received, message.sent, task.requested, task_paused, task_resumed, task_cancelled |
| **Ошибки** | VOICE_INPUT_INVALID, VOICE_CHANNEL_UNAVAILABLE |

### 2.15. FORGE — артефакты

| Поле | Значение |
|---|---|
| **Ответственность** | Управление кодом/патчами, документами, CAD/3D, изображениями, аудио/видео, конфигами, Skills, тестами, пакетами; временные файлы и атомарная запись; diff, предыдущие версии, manifest, integrity checks, связь с задачей, форматную проверку, rollback где возможен, export/archive; Git при наличии, snapshots для не-Git артефактов |
| **Входы** | Результаты действий от CORE/WINGS/BRIDGES; команды пользователя |
| **Выходы** | Версионированные артефакты с integrity hash и связью с task ID; diff; snapshots |
| **Запретные обязанности** | Не заменяет Git (Git при наличии — primary; FORGE — fallback snapshots); не выполняет действия на внешних системах |
| **События** | artifact.created, artifact.updated, artifact.versioned, artifact.exported |
| **Ошибки** | ARTIFACT_WRITE_FAILED, ARTIFACT_INTEGRITY_FAILED, ARTIFACT_ROLLBACK_FAILED |

### 2.16. SKILLS — процедурное знание

| Поле | Значение |
|---|---|
| **Ответственность** | Процедурное знание и workflow-пакеты; manifest с ID, версией, описанием, допустимыми типами задач, prerequisites, capabilities, risk profile, provenance, тесты; маленькие компонуемые Skills; не загружать все сразу; показывать активные Skills; отслеживать версии; отключить Skill независимо от интеграции; выявлять конфликты инструкций |
| **Входы** | Manifest/SKILL.md от пользователя/Tool Studio; зависимости от WINGS capabilities; тесты от LAB |
| **Выходы** | Нормализованные workflow-инструкции для CORE; Skill template для BRIDGES |
| **Запретные обязанности** | Не изменяет глобальные инструкции; не выдаёт автоматически права; не выполняет действия напрямую |
| **События** | skill.loaded, skill.disabled, skill.version_changed, skill.conflict_detected |
| **Ошибки** | SKILL_MANIFEST_INVALID, SKILL_DEPENDENCY_MISSING, SKILL_CONFLICT |

### 2.17. LAB — лаборатория

| Поле | Значение |
|---|---|
| **Ответственность** | Оценка моделей, tool calling, планов, восстановления, Skills, совместимости интеграций, memory retrieval, скорости, стоимости, доли реальных результатов; фиксация версий (runtime/prompt/model/Skill/adapter), сценария, параметров, результата, токенов, стоимости, ошибок, артефактов |
| **Входы** | Golden scenarios; доступ к CORE, MODEL LAYER, WINGS, SKILLS, BRIDGES |
| **Выходы** | Отчёты о benchmark/регрессии; quality signals для COMPASS; regression status |
| **Запретные обязанности** | Не влияет на runtime напрямую (результаты — данные, не инструкции); не выполняет пользовательские задачи |
| **События** | eval.run_started, eval.run_completed, eval.result_recorded |
| **Ошибки** | EVAL_TIMEOUT, EVAL_CONFIG_INVALID, EVAL_RESULT_MISMATCH |

### 2.18. OBSERVATORY — события и диагностика

| Поле | Значение |
|---|---|
| **Ответственность** | Структурированные события (timestamp, task/session ID, component, severity, type); маскировка секретов; ротация журналов; экспорт диагностического пакета; хранение полных конфиденциальных файлов запрещено без разрешения |
| **Входы** | События от всех компонентов; запросы на экспорт логов |
| **Выходы** | Доступ к event log; diagnostic package; read-only audit mode |
| **Запретные обязанности** | Сбой необязательной аналитики не должен ломать исполнение (event bus — fire-and-forward, не blocking); не хранит секреты; не управляет задачами |
| **События** | (собственно — consumer событий; публикует events об изменении состояния OBSERVATORY) |
| **Ошибки** | LOG_ROTATION_FAILED, DIAGNOSTIC_EXPORT_FAILED, EVENT_LOSS_DETECTED |

### 2.19. PULSE — состояние системы

| Поле | Значение |
|---|---|
| **Ответственность** | Здоровье CORE, endpoints моделей, MCP, адаптеров и приложений, индексации MEMORY, фоновых задач; статусы: ONLINE, DEGRADED, OFFLINE, STARTING, STOPPING, UNKNOWN |
| **Входы** | Health check от MODEL LAYER, MCP GATEWAY, BRIDGES, MEMORY, CORE |
| **Выходы** | Пульс-статус для UI; уведомления при смене статуса |
| **Запретные обязанности** | Не выполняет health check за других (только агрегирует); не управляет задачами |
| **События** | pulse.status_changed, pulse.health_check_failed |
| **Ошибки** | PULSE_AGGREGATION_FAILED |

### 2.20. VESSEL — desktop-оболочка

| Поле | Значение |
|---|---|
| **Ответственность** | Desktop-оболочка и рабочий интерфейс; Workbench, Projects, Files, Tasks, Bridges, Skills, Setup; Boot Ritual; темы (semantic tokens), локализация, Reduced Motion; панели (Projects/Work/Files); keyboard navigation, accessibility |
| **Входы** | Данные от CORE API (task state, events, status); команды пользователя |
| **Выходы** | Пользовательский интерфейс; команды, переданные в CORE |
| **Запретные обязанности** | Не редактирует БД напрямую; не обходит AEGIS; не читает секреты напрямую; не выполняет действия на внешних системах |
| **События** | (отображает события CORE/OBSERVATORY; публикует UI events) |
| **Ошибки** | UI_RENDER_FAILED, LOCALIZATION_MISSING, ACCESSIBILITY_VIOLATION |

### 2.21. REGISTRY — реестр компонентов

| Поле | Значение |
|---|---|
| **Ответственность** | Единый реестр проектов, моделей, Skills, интеграций и компонентов; ID, version, provenance, compatibility range, source, license, installation date, permissions; schema_migrations для БД |
| **Входы** | Metadata от всех компонентов (SANCTUM, SKILLS, BRIDGES, MCP GATEWAY, MODEL LAYER); миграции БД |
| **Выходы** | Queryable registry (поиск по ID/типу/версии); compatibility checks; version diff |
| **Запретные обязанности** | Не управляет runtime-поведением компонентов; не выполняет действия; не хранит конфигурацию (только metadata) |
| **Владелец состояния** | REGISTRY владеет metadata-записями (ID, version, provenance, compatibility) и схемой миграций БД. Доменные модули владеют своим специфичным содержимым (capabilities у BRIDGES, тесты у SKILLS). |
| **События** | registry.component_registered, registry.version_changed, registry.compatibility_check |
| **Ошибки** | REGISTRY_CONFLICT, REGISTRY_INTEGRITY_FAILED |

### 2.22. APOCRYPHA — экспериментальная зона

| Поле | Значение |
|---|---|
| **Ответственность** | Изоляция новых способов маршрутизации, экспериментальной памяти, multi-agent стратегий, прототипов Computer Use, self-modifying Skills, недоказанных способов управления программами; не включается автоматически в стабильный runtime; не требует миграции системы при удалении |
| **Входы** | Экспериментальные функции; feature flags из REGISTRY |
| **Выходы** | Прототипы, протестированные в изоляции; данные для переноса в стабильные модули (после подтверждения) |
| **Запретные обязанности** | Не влияет на стабильный runtime без явного feature flag; не требует миграции системы; не выставляет API наружу |
| **События** | apocrypha.experiment_started, apocrypha.experiment_completed, apocrypha.feature_promoted, apocrypha.feature_retired |
| **Ошибки** | APOCRYPHA_ISOLATION_BREACH, EXPERIMENT_UNSAFE |

---

## 3. Слои зависимостей

### 3.1. Таблица слоёв

| Слой | Модули |
|---|---|
| 0 | CONTRACTS (общие типы, ошибки, события, ID, схемы) — не подсистема, а общие контракты |
| 1 | OBSERVATORY, PULSE |
| 2 | SANCTUM |
| 3 | REGISTRY |
| 4 | MODEL LAYER |
| 5 | MEMORY, ARCHIVE, EXPERIENCE, INSTINCTS |
| 6 | AEGIS |
| 7 | WINGS |
| 8 | MCP GATEWAY, BRIDGES, EYES, FORGE, SKILLS |
| 9 | COMPASS, LAB |
| 10 | CORE |
| 11 | VOICE |
| 12 | VESSEL |
| 13 | APOCRYPHA (feature-flagged extension zone) |

**Слой 13 не является «более высоким» в смысле привилегий.** APOCRYPHA зависит только от слоёв < 13 и обязана не зависеть от VESSEL (12) и VOICE (11): экспериментальный UI, если он нужен, проходит через те же точки расширения VESSEL, что и стабильный. Иначе эксперимент нельзя отключить, не тронув оболочку (§4.18: удаление APOCRYPHA не должно требовать миграции всей системы).

### 3.2. Правила зависимостей

1. **Зависимость только вниз по слою.** Слой N может зависеть от слоёв < N.
2. **Перекрёстные связи — только через интерфейсы из CONTRACTS.** Запрещён прямой импорт соседнего слоя.
3. **Dependency inversion для WINGS:** WINGS зависит от `ToolProvider` интерфейса (слой 0). MCP GATEWAY и BRIDGES реализуют `ToolProvider` и регистрируются через DI. WINGS НЕ импортирует MCP GATEWAY/BRIDGES напрямую.
4. **LAB не импортируется CORE.** CORE читает результаты LAB через БД/Registry (слой 3), а не через импорт. COMPASS может использовать quality signals из REGISTRY.
5. **APOCRYPHA зависит от стабильных слоёв через interface-границу.** Стабильные модули НЕ импортируют APOCRYPHA.
6. **VESSEL не читает БД напрямую.** Все изменения идут через API CORE/SANCTUM.
7. **MODEL LAYER не зависит от CORE/COMPASS.** Только от CONTRACTS и SANCTUM.
8. **AEGIS не зависит от CORE/WINGS.** Только от CONTRACTS, SANCTUM, REGISTRY.
9. **MEMORY не владеет Task State.** CORE владеет Task State, MEMORY может индексировать, но не изменять.
10. **Сборка через один composition root.** Не multiple entry points.

### 3.3. Запрещённые циклы

| Цикл | Причина | Разрешение |
|---|---|---|
| CORE → WINGS → CORE | WINGS реализует через интерфейс | WINGS зависит от ToolProvider интерфейса в CONTRACTS |
| COMPASS → CORE → COMPASS | COMPASS маршрутизирует внутри цикла | COMPASS зависит только от MODEL LAYER, REGISTRY, SANCTUM |
| MEMORY → CORE → MEMORY | CORE управляет lifecycle задач, MEMORY хранит данные | Task State — CORE, Storage — MEMORY, интерфейс в CONTRACTS |
| LAB → CORE → LAB | LAB оценивает CORE | LAB читает результаты через БД/Registry, не импортирует CORE |
| VESSEL → CORE → VESSEL | VESSEL отображает CORE | VESSEL читает API CORE, не импортирует внутренние модули CORE |
| AEGIS → WINGS → AEGIS | WINGS спрашивает AEGIS | AEGIS зависит от CONTRACTS, WINGS зависит от AEGIS (downward) |
| BRIDGES → WINGS → BRIDGES | WINGS вызывает BRIDGES через интерфейс | WINGS зависит от ToolProvider интерфейса |

---

## 4. Разделение данных

### 4.1. Конфигурация (SANCTUM / файлы)

| Файл | Содержание |
|---|---|
| `config/system.yaml` | Системные ограничения безопасности |
| `config/runtime.yaml` | Настройки runtime |
| `config/models.yaml` | Описание моделей |
| `config/providers.yaml` | Провайдеры (endpoint, auth) |
| `config/routing.yaml` | Правила маршрутизации |
| `config/mcp.yaml` | MCP-серверы |
| `config/integrations.yaml` | Интеграции |
| `config/permissions.yaml` | Исходные политики AEGIS |
| `config/privacy.yaml` | Privacy policy |
| `config/paths.yaml` | Пути |
| `config/ui.yaml` | Тема, локализация |
| `identity/identity.yaml` | Профиль |
| `identity/personality.md` | Тон личности |
| `identity/system_prompt.md` | Системные инструкции |
| `identity/response_style.md` | Стиль ответа |
| `identity/user_preferences.md` | Предпочтения пользователя |
| `skills/*/manifest.yaml` + `SKILL.md` | Профиль и инструкции Skills |
| `integrations/*/manifest.yaml` | Интеграции (Compatibility Registry) |
| `themes/*/tokens.yaml` | Design tokens |
| `locales/*/ui.json`, `boot.json`, `errors.json` | Локализация |

### 4.2. Динамическая БД (SQLite)

| Сущность | Содержание |
|---|---|
| `schema_migrations` | Версии миграций |
| `projects`, `project_roots` | Реестр проектов |
| `files`, `symbols` | Индексация |
| `documents`, `document_chunks` | Документный поиск |
| `memories`, `memory_sources` | Записи памяти с provenance |
| `tasks`, `task_steps`, `task_dependencies` | Задачи и планы |
| `sessions`, `messages` | Сессии и сообщения |
| `tool_calls`, `tool_results` | История вызовов инструментов |
| `checkpoints`, `artifacts` | Точки восстановления |
| `integrations` (runtime state) | Состояние интеграций (health, status) |
| `integration_versions` | История версий |
| `capabilities` | Registry capability IDs |
| `skills` (registry state) | Registry Skills |
| `providers` (runtime health) | Health провайдеров |
| `model_profiles` | Runtime model profiles |
| `policy_rules` | Нормализованные/кэшированные правила (из permissions.yaml) |
| `approvals` | pending approvals |
| `events` | События OBSERVATORY |
| `eval_runs`, `eval_results` | Результаты LAB |

### 4.3. Артефакты (файловая система)

| Путь | Содержание |
|---|---|
| `artifacts/` | Артефакты задач |
| `models/` | Модели (если локальные) |
| `sandbox/` | Изолированная среда |
| `logs/` | Журналы |
| `data/` | SQLite БД (по умолчанию data/seraphim.sqlite) |

### 4.4. Секреты

| Источник | Местоположение |
|---|---|
| API keys, токены | Защищённое хранилище ОС (Windows Credential Manager) или зашифрованный файл внутри корня |
| Реализация S09 | `SecretStore`; backend по умолчанию — Windows DPAPI (шифртекст в `<root>/data/secrets/<ref>.bin`); при отсутствии безопасного backend — fail-closed (`SECRET_STORE_UNAVAILABLE`), plaintext-fallback отсутствует |
| В конфиге | только `secret_ref` (логическое имя, `^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$`); literal-ключ в конфиге → `SECRET_REF_INVALID`; для `mcp.servers[].env`/`command` literal-секрет отвергается тем же кодом |
| Не хранится в: | YAML-конфиг, SQLite, логи, экспорты (по умолчанию), фикстуры тестов |
| В экспорте | `secret_ref` (ссылка) и метаданные backend; значение не включается (`secrets.included = false`); builder вызывает свой verifier и отказывается возвращать payload с секретом (`DIAGNOSTIC_EXPORT_FAILED`) |
| Значение прочитано процессом | регистрируется process-wide (`register_known_secret`); `sanitize_text`/`sanitize_dict` (ошибки, логи, события, экспорт) удаляют его точным совпадением, независимо от формата |
| Под `*_ref`-ключом | сохраняется только reference-образное значение; всё прочее (пробелы, uppercase, разделители пути, распознанный формат ключа, не-строка) → `[REDACTED]` |
| Перед внешней передачей | privacy gate: `evaluate_transmission` / `assert_transmission_allowed` (по умолчанию внешняя передача запрещена) |

### 4.5. Кэш

| Путь | Содержание |
|---|---|
| `mcp/cache/` | Кэш MCP discovery |
| `models/cache/` | Кэш моделей |
| `memory/exports/` | Экспорты памяти |

---

## 5. Trust boundaries

| ID | Граница | Описание |
|---|---|---|
| TB-0 | Пользователь → SERAPHIM | GUI/CLI — одна валидация; без аутентификации (локальный) |
| TB-1 | Внешний мир → MODEL LAYER | Ответы моделей — недоверенные; не инструкции |
| TB-2 | Недоверенные данные → контекст модели | Файлы, веб, MCP, Skills, память — потенциальный prompt injection |
| TB-3 | Модель → CORE | Предложения модели не имеют прав; только запросы |
| TB-4 | CORE → AEGIS → WINGS | Единственный путь к побочным эффектам |
| TB-5 | SERAPHIM ↔ MCP/адаптер | Quarantine, least privilege, provenance check |
| TB-6 | SERAPHIM → ФС/сеть/process | Разрешённые корни, лимиты CPU/памяти/тайм-ауты |
| TB-7 | Секреты → наружу | Защищённое хранилище; redaction в логах и экспортах |
| TB-8 | APOCRYPHA ↔ стабильный runtime | Feature flag isolation; no automatic promotion |
| TB-9 | Данные пользователя → наружу | Privacy policy определяет передачу; выбор пользователя |
| TB-10 | identity/*.md → SANCTUM | identity-файлы (personality.md, system_prompt.md) — недоверенные данные, не инструкции. §12.3 spec: «Нельзя незаметно менять политику вслед за personality.md или Skill». Валидация SANCTUM — граница между пользовательскими инструкциями и системной политикой. |

---

## 6. Версионирование контрактов

### 6.1. Правила

- Каждый контракт имеет `schema_version` (целое число).
- **Minor** (совместимое): добавление опционального поля. Consumer: сохраняет, игнорирует.
- **Major** (несовместимое): удаление поля, изменение смысла, добавление обязательного поля. Новый ID версии контракта.
- **Не менять смысл capability при сохранении ID** (§17 спецификации).
- Unknown required field (major version N+1) → явная ошибка `CONTRACT_VERSION_UNSUPPORTED`, не молчаливый игнор.
- Unknown optional field → round-trip safe: сохранить и игнорировать.

### 6.2. Миграции БД

- Нумерованные, транзакционные, идемпотентные.
- Таблица `schema_migrations` для отслеживания.
- Миграции добавляются вместе с рабочими сценариями (§6.2).
- Сбой миграции не оставляет полусозданную схему (транзакция).
- Откат: через backup-restore.

### 6.3. Конфигурация

- Миграция конфига — явная команда `seraphim config validate` (§12.4).
- Неизвестные ключи → ошибка валидации с указанием файла/ключа.
- Приоритет: системные ограничения безопасности > пользовательская конфигурация > workspace > временные параметры задачи > defaults (§12.3).

---

## 7. Формат ошибок

Согласно §14.2 спецификации:

```json
{
  "code": "INTEGRATION_TIMEOUT",
  "message_key": "errors.integration_timeout",
  "component": "bridges.freecad",
  "retryable": true,
  "user_action_required": false,
  "details_ref": "event_..."
}
```

Правила:
- UI строит текст по `message_key` + locale.
- `code` — стабильный идентификатор (UPPERCASE, с префиксом модуля при необходимости).
- `message_key` — ключ локализации `errors.<code_lowercase>`.
- `component` — путь к компоненту (dot-separated).
- `retryable` — можно ли повторить автоматически.
- `user_action_required` — требуется ли вмешательство пользователя.
- `details_ref` — ссылка на событие в OBSERVATORY с полными деталями.
- Stack trace и секреты — только в диагностике, не в UI.

---

## 8. Формат событий

Согласно §4.16 и §14.3 спецификации:

Обязательные поля:
- `id` — UUID
- `timestamp` — ISO 8601
- `type` — `<domain>.<object>[.<action>]` в прошедшем времени (2 или 3 части). Примеры из спецификации: `task.created`, `tool.call.started`, `policy.decision`, `memory.retrieval`, `skill.loaded`, `integration.health_changed`, `verification.result`, `checkpoint.created`, `recovery.started`.
- `task_id` / `session_id` — correlation
- `component` — источник (dot-separated path)
- `severity` — INFO, WARN, ERROR, CRITICAL
- `schema_version` — версия формата события
- `correlation_id` — для tracing
- `payload` — безопасный, без секретов

**Базовый set событий** (из §4.16 спецификации):
`task.created`, `task.started`, `task.completed`, `step.started`, `tool.call.started`, `tool.call.completed`, `tool.call.failed`, `policy.decision`, `verification.result`, `memory.retrieval`, `checkpoint.created`, `recovery.started`, `integration.health_changed`, `skill.loaded`

Каждая подсистема определяет **дополнительные события** в своём паспорте (§2). Дополнительные события имеют ту же структуру `<domain>.<object>.<action>` или `<domain>.<object>`, где domain совпадает с именем подсистемы (например, `sandbox.process_killed`, `apocrypha.experiment_started`).

---

## 9. Namespace capability IDs

Согласно §4.9 и §7.4 спецификации:

Формат: `<domain>.<subdomain>.<action>`

Примеры:
- `filesystem.read_file`
- `filesystem.write_file`
- `shell.execute`
- `cad.geometry.inspect`
- `cad.feature.create`
- `cad.document.save`
- `browser.tab.open`
- `browser.page.screenshot`
- `application.connect`
- `screen.capture`

Правила:
- Префикс домена — регистрозависимый, lowercase.
- Каждый capability имеет стабильный ID, описание, входную/выходную схему, permissions, side_effects, timeout, cancel/dry-run support, expected_errors, postcondition check, compatible_versions (§7.4).
- Новый capability — новый ID. Нельзя переиспользовать ID с другим смыслом.

---

## 10. Definition of Done (на уровне контракта)

Компонент готов, когда:
- [ ] Определён его контракт/manifest и схема конфигурации
- [ ] Ошибки структурированы (envelope §14.2)
- [ ] Есть happy path и failure tests
- [ ] Permissions объявлены
- [ ] Секреты очищаются из логов
- [ ] Действие отменяется либо явно объявлено, что отмена недоступна
- [ ] Пользователь может увидеть и отключить компонент
- [ ] Есть install/uninstall документация
- [ ] Изменяющие состояние действия имеют проверку постусловия
- [ ] Ошибки видны через UI/CLI
- [ ] Версия и совместимость указаны
- [ ] Компонент публикует события в OBSERVATORY (дополнение к §20.3 spec)

---

## 11. Разрешённые конфликты спецификации и контрактные решения

### 11.1. MEMORY vs ARCHIVE vs EXPERIENCE vs INSTINCTS

- **Факт:** §2 определяет их как отдельные модули; §4.6 перечисляет их как слои MEMORY; §27 помещает ARCHIVE/EXPERIENCE/INSTINCTS под MEMORY.
- **Решение контракта:** MEMORY владеет storage/retrieval API для всех memory-слоёв. ARCHIVE владеет логикой долговременного хранения и архивирования. EXPERIENCE/INSTINCTS — логика извлечения наблюдений. CORE владеет Task State, MEMORY может индексировать но не изменять.
- **Статус:** ACCEPTED — зафиксировано спецификацией §4.6, §3.1. Требуется подтверждение на C1.

### 11.2. REGISTRY без отдельного раздела в спецификации

- **Факт:** REGISTRY есть в §2 (словарь) и упоминается в §4.8, §4.9, §16, но не имеет собственного раздела в §4.
- **Решение контракта:** REGISTRY — shared metadata service для всех компонентов. Каждый компонент (SKILLS, BRIDGES, MCP GATEWAY, MODEL LAYER) владеет своим доменным metadata; REGISTRY предоставляет общий identity/version/provenance/compatibility.
- **Статус:** PROPOSED — требует подтверждения на C1.

### 11.3. WINGS vs MCP GATEWAY vs BRIDGES

- **Факт:** §27 помещает MCP GATEWAY и BRIDGES под WINGS; §2 и §3 показывают их как периферийные модули.
- **Решение контракта:** WINGS — единственный внутренний слой вызова инструментов. MCP GATEWAY и BRIDGES — implementers `ToolProvider` интерфейса, регистрируются через DI. WINGS не импортирует их напрямую.
- **Статус:** ACCEPTED — dependency inversion, стандартный паттерн.

### 11.4. VOICE vs VESSEL

- **Факт:** VOICE управляет диалоговым каналом; VESSEL — оболочка. Неясно, где рендерится чат.
- **Решение контракта:** VOICE управляет семантикой диалога (вход/выход сообщений). VESSEL рендерит UI чата. VOICE не зависит от VESSEL.
- **Статус:** PROPOSED — требует подтверждения на C1.

### 11.5. FORGE vs WINGS filesystem tools

- **Факт:** WINGS выполняет filesystem read/write; FORGE управляет версионированными артефактами.
- **Решение контракта:** WINGS выполняет операцию записи. FORGE регистрирует результат как версионированный артефакт. FORGE не выполняет запись напрямую.
- **Статус:** ACCEPTED — разделение ответственности, очевидное из спецификации.

### 11.6. policy_rules в БД (§6.2) и permissions.yaml в конфиге (§12.2)

- **Факт:** Конфликтующие места хранения.
- **Решение контракта:** Исходная политика — файл `permissions.yaml` (SANCTUM). Нормализованные/кэшированные правила и pending approvals — БД.
- **Статус:** PROPOSED — требует подтверждения на C1.

---

## 12. Открытые вопросы

Полный список ADR с вариантами и статусами — в `ARCHITECTURE_DECISIONS.md`. Здесь вопросы сгруппированы по сроку решения. ADR-000 (формат ADR) принят и здесь не перечислен.

### 12.1. Требуют прототипа — решение на S02, блокируют S03

| ADR | Вопрос | Почему нельзя решить без прототипа |
|---|---|---|
| ADR-001 | Язык backend (Python / Rust / C# / гибрид) | §18 прямо требует прототипа; нужно проверить MCP IPC, subprocess с лимитами, упаковку |
| ADR-002 | Desktop framework (Tauri / Electron / нативный) | §18 прямо требует прототипа; нужно измерить анимации, round-trip до backend, доступ к локальным путям |
| ADR-003 | Транспорт GUI↔CORE (in-process / loopback HTTP / IPC) | Производен от ADR-001 и ADR-002 |
| ADR-013 | Структура пакетов и проверка границ зависимостей | Производен от ADR-001 (инструмент проверки зависит от языка) |
| ADR-014 | Single-process vs вынос недоверенного кода | Требует проверки ADR-005 на целевой среде |

### 12.2. Требуют проверки среды или выбора пользователя

| ADR | Вопрос | Что нужно от пользователя / среды |
|---|---|---|
| ADR-005 | Изоляция shell / MCP / адаптеров | Проверка, что выборочная изоляция работает на Windows 11 Home без админских прав |
| ADR-006 | Секреты и локальные модели | **Секреты решены в S09** (DPAPI-файл внутри корня через `SecretStore`; подтвердить или выбрать Credential Manager). Открыто: запускает ли SERAPHIM локальный сервер модели |
| ADR-017 | Повторное использование кода ProjectMemory | Существует ли этот код вне репозитория и под какой лицензией (§4.6 упоминает его как существующий) |

### 12.3. Контрактные вопросы — решение на C1

| ADR / раздел | Вопрос |
|---|---|
| ADR-015, §11.6 | policy_rules в БД (§6.2 spec) vs permissions.yaml (§12.2 spec) — единый источник истины |
| ADR-016, §11.2 | REGISTRY не имеет раздела в §4 спецификации: границы и отношение к доменным реестрам SKILLS/BRIDGES/MODEL LAYER |
| §11.4 | VOICE vs VESSEL: где живёт рендеринг чата |
| ADR-010 | Обязательный security test suite: включать ли golden-сценарии в CI с этапа, вводящего возможность |
| ADR-011, §9 | Namespace capability IDs: подтверждение проекта решения (смешанный формат из примеров спецификации) |

### 12.4. Поздние решения — не блокируют S03

| ADR | Вопрос | Срок |
|---|---|---|
| ADR-004 | Сериализация схем и версия manifests | S04 |
| ADR-007 | SQLite schema strategy и backup | S05 |
| ADR-008 | Формат Skills | S34 |
| ADR-009 | Стратегия GUI automation | S63 |
| ADR-012 | Обновление бинарника и интеграций | S73 |

### 12.5. Пробелы спецификации (не ADR, а недостающие требования)

| Пробел | Где | Что нужно |
|---|---|---|
| REGISTRY не описан в §4 | §2 vs §4 | Определить раздел-источник ответственности (см. ADR-016) |
| Не определён формат Integration Manifest как схемы | §4.9 («концептуальный пример») | Формальная JSON Schema + миграции (S41) |
| Не определён формат Integration Manifest как схемы | §4.9 («концептуальный пример») | Формальная JSON Schema + миграции (S41) |
| Не указано, кто авторитетен при конфликте tool ID из разных источников | §4.8, §4.10 | Правило разрешения конфликтов имён (S38) |
| Не определено поведение при недоступности OBSERVATORY | §3.1 | Явный контракт деградации (S06) |

---

*Конец CONTRACTS.md S01.*
