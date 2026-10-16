# SERAPHIM — IMPLEMENTATION_PLAN

**Версия:** 0.1
**Дата:** 13 октября 2026 (этап S01)
**Статус:** PROPOSED — подтверждается на C1
**Источники:** `SERAPHIM_Full_Architecture_Spec.md` §21 (фазы), §22 (MVP), §20.2 (golden сценарии); `SERAPHIM_Implementation_Prompt_Chain.md` (этапы S00–S77 и контрольные точки C0–C23); `CONTRACTS.md` (границы); `ARCHITECTURE_DECISIONS.md` (гейты решений).

---

## 0. Правила плана

1. **Один этап за раз.** Этапы выполняются строго по номерам. Следующий этап не начинается до приёмки текущего (или до явного решения пользователя продолжить с известными дефектами).
2. **Не более двух подсистем за этап.** Ни один этап не вводит полную поверхность всех подсистем. Матрица «подсистема → первый этап» в §2 это подтверждает.
3. **Каждый этап заканчивается проверяемым артефактом:** тестом, командой или документом с воспроизведением.
4. **Гейт ADR.** Этап не начинается, если его блокирующий ADR не принят. Блокирующие ADR указаны в столбце «Гейт».
5. **Checkpoint не реализует.** C0–C23 — только проверка и вердикт (`READY TO COMMIT` / `NEEDS MANUAL REVIEW` / `BLOCKED`).
6. **MVP-гейт.** Раздел 22 спецификации: фазы, помеченные `ПОСЛЕ MVP`, не начинаются, пока не пройден C8 (рабочий вертикальный сценарий через CLI).
7. **Запрещено заранее:** microservices, Kubernetes, распределённые очереди, обязательная vector DB, маркетплейс, multi-user/cloud sync, собственный генератор изображений, свободное GUI-управление, автогенерация MCP для любой программы, автономная перезапись identity/prompt, автоматическое принятие Instincts (§22 «Отложить»).

---

## 1. Карта блоков

| Блок | Этапы | Контрольные точки | Подсистемы блока |
|---|---|---|---|
| A. Разведка | S00 | C0 | — |
| B. Архитектура и стек | S01–S02 | C1 | CONTRACTS, ADR |
| C. Backend foundation | S03–S06 | C2 | CONTRACTS, REGISTRY (миграции), OBSERVATORY, PULSE |
| D. SANCTUM и CLI | S07–S11 | C3, C4 | SANCTUM, CLI |
| E. MODEL LAYER и COMPASS | S12–S15 | C5 | MODEL LAYER, COMPASS |
| F. CORE / WINGS / AEGIS | S16–S27 | C6, C7, C8 | CORE, WINGS, AEGIS, FORGE (минимально) |
| G. REGISTRY / ProjectMemory / MEMORY | S28–S33 | C9, C10 | REGISTRY, MEMORY |
| H. SKILLS | S34–S36 | C11 | SKILLS |
| I. MCP GATEWAY | S37–S40 | C12 | MCP GATEWAY |
| J. BRIDGES | S41–S47 | C13, C14 | BRIDGES |
| K. VESSEL / UI | S48–S60 | C15, C16, C17 | VESSEL, VOICE, PULSE UI |
| L. EYES и FORGE | S61–S66 | C18, C19 | EYES, FORGE |
| M. LAB, обучение, эксперименты | S67–S72 | C20, C21 | LAB, EXPERIENCE, INSTINCTS, APOCRYPHA |
| N. Надёжность и релиз | S73–S77 | C22, C23 | ARCHIVE (backup), всё системно |

---

## 2. Матрица «подсистема → первый этап, где она появляется»

Доказательство, что план не делает все подсистемы одновременно.

| Подсистема | Первый этап | Полная поверхность к этапу |
|---|---|---|
| CONTRACTS (типы/ошибки/события) | S01 (контракт) / S04 (код) | S06 |
| REGISTRY | S05 (миграции) | S28 |
| OBSERVATORY | S06 | S59 (UI) |
| PULSE | S06 (агрегация) | S59 (UI) |
| SANCTUM | S07 | S55 (UI) |
| CLI | S10 | S27 |
| MODEL LAYER | S12 | S56 (UI) |
| COMPASS | S15 | S56 (UI) |
| CORE | S16 | S27 |
| WINGS | S19 | S57 (UI) |
| AEGIS | S20 | S75 (red-team) |
| FORGE | S25 (evidence refs) / S65 (полная) | S65 |
| MEMORY / ProjectMemory | S29 | S58 (UI) |
| ARCHIVE | S74 | S74 |
| SKILLS | S34 | S58 (UI) |
| MCP GATEWAY | S37 | S57 (UI) |
| BRIDGES | S41 | S47 |
| VESSEL | S48 | S60 |
| VOICE | S48 (чат-канал) | S60 |
| EYES | S61 | S64 |
| LAB | S67 | S68 |
| EXPERIENCE / INSTINCTS | S69 / S70 | S70 |
| APOCRYPHA | S72 | S72 |

---

## 3. Этапы

### Блок A. Разведка

**S00 — Аудит репозитория без изменений** · ВЫПОЛНЕН
- Подсистемы: —
- Критерии завершения: аудит отделяет факты от предположений и содержит команды/выводы · нет изменений production-кода и зависимостей · ясно перечислены решения, требующие прототипа или согласования.
- Факт: `AUDIT_REPORT.md`, статус PASS.

**C0 — CHECKPOINT: аудит и готовность к проектированию** · ВЫПОЛНЕН (репозиторий инициализирован, коммит `0e87cec`)

### Блок B. Архитектура и стек

**S01 — Архитектурный контракт и ADR** · ВЫПОЛНЕН
- Подсистемы: CONTRACTS (описание всех 22), ADR, план.
- Критерии завершения: у каждой подсистемы описаны ответственность, входы/выходы и запретные обязанности · план разбит на маленькие этапы с критериями завершения · непроверенные предположения и конфликтующие требования обозначены явно.
- Гейт ADR: нет (сам создаёт ADR-файл).
- Не входит: любой прикладной код, выбор языка, выбор framework, схемы БД в коде.

**S02 — Технологический прототип и выбор стека** · ВЫПОЛНЕН
- Подсистемы: — (изолированный прототип вне production).
- Критерии завершения: выбор подтверждён воспроизводимыми результатами, а не вкусом · прототип изолирован от production и не становится неявной зависимостью · описан план удаления/переноса прототипа.
- Закрывает: ADR-001 (Python backend), ADR-002 (Electron VESSEL), ADR-003 (HTTP/loopback); готовит ADR-005 (Job Object isolation работает), ADR-013, ADR-014.
- Не входит: реальные модели, секреты, production-миграция.

**C1 — CHECKPOINT: архитектура и технологические решения**
- Проверяет: границы модулей, отсутствие циклических обязанностей, ясность контрактов, доказательства выбора стека, отделение открытых вопросов от принятых ADR.
- Обязателен перед S03. Вердикт gates: ADR-001/002/003/013/014 приняты.

### Блок C. Backend foundation

**S03 — Скелет репозитория и сборка** · ВЫПОЛНЕН · Гейт: C1 (ADR-001, 002, 003, 013, 014)
- Подсистемы: структура пакетов, tooling.
- Критерии завершения: чистая сборка и запуск работают по документации · быстрые проверки доступны одной командой или документированным набором · нет секретов, node_modules, виртуальных окружений, случайных бинарников или прототипного мусора в git.
- Не входит: агентные функции, БД, модель, UI-экраны.

**S04 — Базовые схемы, типы и ошибки** · ВЫПОЛНЕН · Гейт: S03, ADR-004
- Подсистемы: CONTRACTS (код).
- Критерии завершения: ошибки единообразны между backend и CLI/UI · некорректный вход даёт понятную ошибку, а не необработанный traceback наружу · все схемы имеют positive и negative tests.
- Факт: `backend/seraphim/contracts/` (10 модулей), 174/174 tests PASS, ruff PASS.

**S05 — SQLite и слой миграций** · ВЫПОЛНЕН · Гейт: S04, ADR-007
- Подсистемы: REGISTRY (миграции, component metadata), Layer 1 storage.
- Критерии завершения: повторный запуск миграций идемпотентен · тесты никогда не используют пользовательскую БД · сбой миграции не оставляет полусозданную схему.
- Факт: `backend/seraphim/storage/` (5 modules + m0001_kernel), 232/232 tests PASS (58 new storage tests), ruff PASS, transactional migrations + parameterized queries + path resolution.

**S06 — Event bus и OBSERVATORY foundation** · Гейт: S05
- Подсистемы: OBSERVATORY, PULSE (агрегация).
- Критерии завершения: история событий переживает рестарт · ошибка необязательного подписчика не ломает producer/CORE · тесты доказывают отсутствие тестового секрета в логах.

**C2 — CHECKPOINT: backend foundation**

### Блок D. SANCTUM и CLI

**S07 — SANCTUM: загрузчик конфигурации** · ВЫПОЛНЕН · Гейт: C2
- Критерии завершения: конфигурация валидируется через одну точку входа · ошибки указывают файл/ключ и способ исправления · CLI и GUI смогут использовать тот же validator.
- Факт: `backend/seraphim/sanctum/{loader.py, validator.py, schemas/}`, `backend/seraphim/cli/{config.py, main.py}`, `backend/seraphim/__main__.py`, CLI command `seraphim config validate`, 281/282 tests PASS (18 new sanctum tests), ruff PASS.

**S08 — SANCTUM: identity и сборка инструкций** · ВЫПОЛНЕН
- Критерии завершения: активные инструкции можно инспектировать без раскрытия секретов · данные из Skill/файла не могут повыситься до system policy · пустые identity files имеют предсказуемые defaults.
- Факт: `backend/seraphim/sanctum/{identity.py, prompt_composer.py}`, `backend/seraphim/cli/identity.py`, шаблон `identity/{identity.yaml, system_prompt.md, personality.md, response_style.md}`, `seraphim identity show|prompt-preview`, 42 new tests (12 identity + 22 composer + 5 snapshot + 3 CLI, 323/324 PASS), ruff PASS. Независимый review (code-reviewer, 2 раунда) — 2 BLOCKER закрыты (циклическая нейтрализация `<<<` с доказанным завершением; метка `source` сводится к безопасному токену — закрыт и `>>>`/`key=value` spoofing), 3 MINOR закрыты, остальные MINOR оставлены осознанно и задокументированы.

**S09 — SANCTUM: секреты, privacy и redaction** · ВЫПОЛНЕН · Гейт: ADR-006 (секреты — ACCEPTED)
- Критерии завершения: export не содержит активных секретов · auth errors не раскрывают значение ключа · privacy policy проверяется перед внешней передачей данных.
- Факт: `backend/seraphim/sanctum/{secrets.py, privacy.py, export.py}`, `backend/seraphim/cli/{secrets.py, errors.py}`, CLI `seraphim secrets set|list|show|rotate|delete|audit` и `seraphim privacy summary`, 125 new tests в четырёх S09-файлах (65 secrets + 25 privacy + 19 export + 16 CLI) плюс +18 в `test_contracts_sanitization.py`/`test_logger.py`/`test_store.py`/`test_loader.py`, 481/482 PASS, ruff PASS. Секреты — только в платформенном хранилище: ADR-006 переведён в ACCEPTED для секретов (вариант 4 — Windows DPAPI через `ctypes`, шифртекст в `<root>/data/secrets/<ref>.bin`, ноль новых зависимостей); при отсутствии безопасного backend — fail-closed (`SECRET_STORE_UNAVAILABLE`), plaintext-fallback отсутствует. В конфиге только `secret_ref`; literal-ключ отвергается (`SECRET_REF_INVALID`), включая `mcp.servers[].env`/`command`. Значение, прочитанное процессом, регистрируется process-wide и удаляется из любого sink'а (ошибки, логи, события/SQLite, экспорт) точным совпадением. Privacy gate по умолчанию запрещающий (`allow_external_transmission=false`). Независимый security-review (read-only): 0 BLOCKER, 3 MAJOR и 4 MINOR — все MAJOR и MINOR закрыты, остаточный риск (энтропийная эвристика для `secret_ref`) задокументирован; подробности — `IMPLEMENTATION_LOG.md`.

**C3 — CHECKPOINT: SANCTUM config, identity, privacy**

**S10 — CLI foundation и doctor**
- Критерии завершения: проблемы диагностики понятны без чтения кода · CLI поддерживает machine-readable сценарии · диагностика не меняет состояние без явной команды.

**S11 — Экспорт, импорт и конфигурационный backup**
- Критерии завершения: импорт не может писать за пределы root · неудачный импорт сохраняет прежний конфиг · экспорт без секретов проходит validation и повторно импортируется.

**C4 — CHECKPOINT: CLI, doctor, backup**

### Блок E. MODEL LAYER и COMPASS

**S12 — MODEL LAYER: provider interface и mock** · Гейт: C4
- Критерии завершения: агентные тесты работают офлайн через FakeProvider · capabilities задекларированы и проверяются · ошибки нормализованы без auth leakage.

**S13 — OpenAI-compatible provider: базовые запросы**
- Критерии завершения: endpoint настраивается конфигурацией, а не исходниками · ошибки понятны и не раскрывают ключ · CI работает offline на mock server.

**S14 — Streaming и нормализация tool calls**
- Критерии завершения: CORE/UI получают единые внутренние события · tool call запускается только после полной валидации аргументов · cancel прекращает последующую обработку.

**S15 — COMPASS: профили и маршрутизация**
- Критерии завершения: роутер объясним и воспроизводим · выбор модели не ослабляет AEGIS/privacy · новый provider добавляется конфигом без изменения CORE.

**C5 — CHECKPOINT: MODEL LAYER и COMPASS**

### Блок F. CORE / WINGS / AEGIS (ядро)

**S16 — Task Engine: модель задачи и state machine** · Гейт: C5
- Критерии завершения: каждый переход документирован и тестируется · нельзя выставить SUCCEEDED без процедуры проверки · состояние не зависит от текста модели.

**S17 — Task/session persistence и resume**
- Критерии завершения: состояние восстанавливается после остановки процесса · повторный resume не дублирует работу · неполные/несовместимые задачи требуют review вместо слепого продолжения.

**S18 — Planner и структурированный план**
- Критерии завершения: план отображается и сохраняется структурированно · некорректный план не начинает частичное выполнение · попытки ремонта формата ограничены.

**S19 — WINGS: registry инструментов и tool contract** · Гейт: ADR-011, ADR-016
- Критерии завершения: вызовы имеют единый формат · описание инструмента доступно CORE и UI · неизвестный или disabled tool не исполняется.

**C6 — CHECKPOINT: Task Engine, persistence, Planner и WINGS contracts**

**S20 — AEGIS: policy engine** · Гейт: C6, ADR-015, ADR-005
- Критерии завершения: каждый tool call проверяется до side effect · policy request содержит достаточный контекст · отказ логируется безопасно и объяснимо.

**S21 — Ограниченные filesystem tools**
- Критерии завершения: нельзя читать/писать за пределами разрешённых roots · секретные пути не читаются и не индексируются без отдельного разрешения · ошибки I/O нормализованы.

**S22 — Ограниченные shell/process tools**
- Критерии завершения: аргументы передаются без shell injection · timeout/cancel реально останавливает процесс и доступных потомков · вывод ограничен и редактируется от секретов.

**S23 — Approval, cancellation и timeout orchestration**
- Критерии завершения: рискованное действие ждёт решения до запуска · approval нельзя повторно применить к другой операции · после отмены статус соответствует фактическому состоянию.

**C7 — CHECKPOINT: AEGIS и безопасные системные инструменты**

**S24 — CORE Executor loop**
- Критерии завершения: task выполняется от goal до tool result · каждый call проходит validation и AEGIS · цикл ограничен и сохраняет события.

**S25 — Verification Engine: постусловия и доказательства**
- Критерии завершения: у результата есть evidence source/time references · провал verification переводит task в retry/failed/blocked по policy · CLI/UI может показать, что именно проверено.

**S26 — Recovery, anti-loop и checkpoints**
- Критерии завершения: неуспешное действие не повторяется бесконечно · recovery не дублирует non-idempotent call с неизвестным результатом · checkpoint позволяет объяснимый resume.

**S27 — Первый end-to-end сценарий через CLI**
- Критерии завершения: golden vertical scenario проходит из чистого test root · negative scenarios доказывают безопасное поведение · events показывают последовательность действий.

**C8 — CHECKPOINT: CORE end-to-end milestone** · **MVP-гейт: до его прохождения блокируются блоки G–N, кроме подготовки документов**

### Блок G. REGISTRY, ProjectMemory, MEMORY · Гейт: C8

**S28 — REGISTRY: проекты и рабочие пространства** · Гейт: ADR-016, ADR-017
- Критерии завершения: удаление из реестра не удаляет исходные данные · реестр сохраняет root policy и её provenance · кириллические/специальные пути обрабатываются корректно.

**S29 — Безопасный project scanner**
- Критерии завершения: доказано, что secret file не читается/не хэшируется · сбой scan не уничтожает прежний индекс · нет stale indexed row после regular file → external symlink.

**S30 — Документный поиск: chunks и SQLite FTS**
- Критерии завершения: результат содержит файл, строки/heading и snippet · русскоязычный поиск проверен · ошибка парсинга не стирает прежние chunks.

**S31 — Индекс символов и навигация по коду**
- Критерии завершения: у symbol есть source/confidence/path/line по возможностям extractor · ошибка extractor не уничтожает прежний индекс · лимит не приводит к потере новых символов из-за неправильного счётчика.

**C9 — CHECKPOINT: Project registry и индексация**

**S32 — MEMORY: записи, provenance и жизненный цикл**
- Критерии завершения: пользователь видит источник и может исправить/удалить запись · автоизвлечённая информация помечена как непроверенная · повторная синхронизация не дублирует записи.

**S33 — MEMORY Context Manager и retrieval pack**
- Критерии завершения: context pack ограничен и детерминирован для одинакового входа · каждый retrieval fragment связан с источником · проектные данные не могут заменять system instructions.

**C10 — CHECKPOINT: MEMORY и Context Manager**

### Блок H. SKILLS · Гейт: C8

**S34 — SKILLS: manifest и валидация** · Гейт: ADR-008
- Критерии завершения: manifest documented/versioned · неизвестные или небезопасные permissions не выдаются · для сторонних пакетов фиксируются source и license.

**S35 — SKILLS: registry, loader и применение**
- Критерии завершения: skill отключается без перезапуска либо limitation documented · несуществующий/запрещённый tool блокируется · активные Skills видны пользователю.

**S36 — Skill Studio v1: создание, тестирование и экспорт**
- Критерии завершения: новый Skill не активируется только потому, что создан моделью · перед активацией доступен diff · экспортируемый пакет повторно валидируется.

**C11 — CHECKPOINT: Skills v1**

### Блок I. MCP GATEWAY · Гейт: C8

**S37 — MCP GATEWAY: безопасный lifecycle клиента** · Гейт: ADR-005, ADR-014
- Критерии завершения: MCP process имеет явный lifecycle/health · неизвестный сервер не запускается скрыто · disable/remove останавливает process и закрывает ресурсы.

**S38 — MCP tool discovery и mapping в WINGS**
- Критерии завершения: tools видны в registry с source/server version · одинаковые имена разных серверов не конфликтуют · все вызовы проходят policy и сохраняют provenance.

**S39 — MCP resources, prompts и health**
- Критерии завершения: resources/prompts доступны через inspect APIs · resource data не становится trusted instruction · падение одного сервера не ломает прочие интеграции.

**S40 — MCP permissions, diagnostics и contract tests**
- Критерии завершения: у каждого MCP есть trust status и permissions · тест безопасен и не исполняет случайный destructive tool · пользователь может отключить/удалить интеграцию.

**C12 — CHECKPOINT: MCP Gateway**

### Блок J. BRIDGES · Гейт: C12

**S41 — BRIDGES: Universal Capability Model и manifest**
- Критерии завершения: manifest валидируется и версионируется · universal API не стирает native capabilities · для стороннего кода есть source/license/permissions.

**S42 — BRIDGES Adapter SDK**
- Критерии завершения: новый adapter создаётся без изменения CORE · contract suite применима к разным adapter types · adapter failure изолирован насколько позволяет выбранный runtime.

**S43 — BRIDGES Registry и lifecycle пакетов**
- Критерии завершения: видны version/source/permissions · регрессивное обновление можно откатить · uninstall не удаляет исходные данные приложения.

**S44 — BRIDGES Test Harness и demo adapter**
- Критерии завершения: success подтверждается postcondition, а не return success · отчёт разделяет passed/failed/not applicable · fake adapter действительно меняет тестовое состояние.

**C13 — CHECKPOINT: BRIDGES core**

**S45 — Импорт существующего MCP как Bridge**
- Критерии завершения: existing MCP подключается без написания новой реализации · import не запускает server скрыто и не выдаёт права без approval · provenance/license сохраняются.

**S46 — Discovery Engine v1: безопасное обнаружение**
- Критерии завершения: discovery не исполняет произвольный найденный код · каждая рекомендация содержит evidence/confidence · нет ложного обещания GUI automation, если найден только экран приложения.

**S47 — Генерация шаблона adapter и Skill Composer**
- Критерии завершения: непроверенный Bridge не становится READY · пользователь видит diff, requested permissions и тесты · повторная генерация не перезаписывает user files.

**C14 — CHECKPOINT: BRIDGES import, discovery, generation**

### Блок K. VESSEL / UI · Гейт: C8, ADR-002

**S48 — VESSEL: UI foundation и дизайн-система**
- Критерии завершения: дизайн-система переиспользуемая и основана на tokens · статусы различаются не только цветом · reduced motion поддержан.

**S49 — Локализация ru/en и accessibility core**
- Критерии завершения: нет новых hardcoded user-facing strings · RU/EN покрывают текущий UI · reduced motion сохраняет функциональность.

**S50 — VESSEL shell, navigation и UI API** · Гейт: ADR-003
- Критерии завершения: UI не дублирует business logic · backend offline виден, reconnect управляем · placeholder screens обозначены честно.

**C15 — CHECKPOINT: VESSEL foundation**

**S51 — Workbench layout** — workbench полезен без анимации и на узком окне · статусы доступны независимо от декора · layout persistence валидируется.
**S52 — UI Projects, Files и Task list** — данные поступают из backend, не из hardcoded mocks · UI различает remove registry entry и delete files · кириллица и длинные пути отображаются корректно.
**S53 — Task timeline, tool calls, approvals и evidence UI** — статус отражает CORE, не декоративный UI timer · risky actions требуют approval до выполнения · пользователь видит доказательства результата.
**S54 — Context/Files и artifact preview panel** — контекст можно inspect-ить без раскрытия секретов · источники имеют line/path refs и freshness state · unsupported preview не вызывает crash.

**C16 — CHECKPOINT: Workbench и прозрачность задач**

**S55 — SANCTUM Settings UI** — identity/prompts редактируются без изменения исходников · UI и CLI используют общий validator · policy-sensitive changes не обходят AEGIS.
**S56 — Models и COMPASS UI** — provider/endpoint меняются без изменения кода · routing reason/privacy scope видны · fallback не активируется скрытно.
**S57 — WINGS, MCP и BRIDGES UI** — видны source и trust каждой интеграции · update/rollback/disable отражают реальный backend state · права не меняются без согласия.
**S58 — SKILLS, MEMORY и ARCHIVE UI** — пользователь контролирует долговременную память · skill валидируется до активации · archive links переживают restart.
**S59 — OBSERVATORY и PULSE UI** — ONLINE означает подтверждённый health check · diagnostic export не раскрывает secrets · сбой OBSERVATORY не ломает CORE.
**S60 — DEUS EX MACHINA: кинематографичный Boot Ritual** — ритуал не маскирует ошибки и имеет возможность пропуска · статусы соответствуют реальным checks · без анимации доступны те же диагностики.

**C17 — CHECKPOINT: Основные экраны VESSEL и Boot Ritual**

### Блок L. EYES и FORGE · Гейт: C8

**S61 — EYES: image/screenshot ingress и evidence store** — изображение имеет provenance/privacy scope · vision capability проверяется, а не предполагается · результат ссылается на конкретный image artifact.
**S62 — Browser integration** — browser actions проходят AEGIS и оставляют evidence · cookies/profile secrets не попадают в prompt/logs по умолчанию · browser имеет health status и может быть отключён.
**S63 — Computer Use abstraction и mock backend** · Гейт: ADR-009 — computer Use не является неограниченным default capability · каждое действие имеет target, correlation и timeout · mock contract тестируется без реального ввода.
**S64 — Visual Verification Engine** — у проверки есть конкретный image reference · low confidence даёт unverified/needs review · failed visual postcondition не считается success.

**C18 — CHECKPOINT: EYES, Browser и Computer Use**

**S65 — FORGE: артефакты, snapshots, diff и export** — пользователь видит provenance артефакта · rollback не перезаписывает изменённый user file без approval · export исключает secrets.
**S66 — Workflow engine и первые полезные Skills** — workflow исполняется через CORE · каждый шаг имеет status и expected output · repeatability/side effects задокументированы.

**C19 — CHECKPOINT: FORGE и workflow primitives**

### Блок M. LAB, обучение, эксперименты · Гейт: C8

**S67 — LAB: golden tasks и benchmark runner** — golden suite работает офлайн · score подкреплён assertions/evidence · failed cases не скрываются в aggregate score.
**S68 — LAB UI и регрессионные отчёты** — отчёт раскрывает failed cases и evidence · несопоставимые окружения сравниваются только с предупреждением · LAB не обязателен для запуска CORE.

**C20 — CHECKPOINT: LAB evaluation**

**S69 — EXPERIENCE: observations по результатам** — каждое observation связано с task evidence · повторяемость не считается доказательством истины · пользователь может отключить сбор и удалить entries.
**S70 — INSTINCTS: эвристики с confidence и review** — instinct не становится active без approval policy · пользователь видит evidence и область применимости · удаление/rollback не ломает runtime.
**S71 — Multi-agent: delegation и handoff** — subagent не повышает свои permissions · есть лимиты глубины, ходов и времени · handoff проверяется независимо.
**S72 — APOCRYPHA: feature flags и experimental registry** — эксперимент отключён по умолчанию · риск/статус и способ отката понятны · rollback возвращает базовое поведение.

**C21 — CHECKPOINT: EXPERIENCE, INSTINCTS, agents и APOCRYPHA**

### Блок N. Надёжность и релиз · Гейт: C8

**S73 — Обновления компонентов и supply chain** · Гейт: ADR-012 — обновление не активируется до валидации · source/version/license/permission diff виден пользователю · rollback подтверждён тестом.
**S74 — Полный backup/restore runtime state** — backup имеет integrity checks · restore в отдельный root не затрагивает текущую установку · после restore проходят doctor и golden E2E.

**C22 — CHECKPOINT: updates и full backup/restore**

**S75 — Security hardening и red-team suite** · Гейт: ADR-010 — критические обходы имеют regression tests · нет известного AEGIS bypass, скрытого за утверждением safe · residual risks documented.
**S76 — Resilience, performance и crash recovery audit** — benchmarks повторяемы и связаны с environment/version · long tasks наблюдаемы и остановимы/возобновляемы, где это заявлено · non-idempotent side effects не повторяются вслепую после crash.
**S77 — Документация, packaging и release readiness** — новый пользователь может поставить и запустить приложение по инструкции · core flows проходят на чистом root · release notes честно перечисляют ограничения · артефакты не содержат secrets/private logs/prototypes/dev-only files.

**C23 — CHECKPOINT: финальный security/release gate**

---

## 4. Golden-сценарии спецификации (§20.2) и этап, где они впервые проверяются

| № | Сценарий | Этап |
|---|---|---|
| 1 | Подключить test model provider | S12–S13 |
| 2 | Создать файл в sandbox и проверить содержимое | S21, S27 |
| 3 | Запретить удаление вне разрешённого корня | S20–S21 |
| 4 | Подключить test MCP и показать tools | S37–S38 |
| 5 | Запустить integration smoke test | S44 |
| 6 | Остановить задачу и проверить прекращение вызовов | S23 |
| 7 | Вызвать timeout и корректно восстановиться | S22–S23 |
| 8 | Продолжить задачу после рестарта CORE | S17 |
| 9 | Не индексировать секретный вложенный каталог | S29 |
| 10 | Не читать внешний symlink за пределами root | S29 |
| 11 | При сбое symbol parser сохранить старый индекс | S31 |
| 12 | Обнаружить цикл одинаковых tool calls | S26 |
| 13 | Выполнить действие в приложении и проверить постусловие | S44 |
| 14 | Переключить ru/en без пропущенных ключей | S49 |
| 15 | Отключить анимацию и проверить Reduced Motion | S48–S49 |
| 16 | Установить Skill без автоматической выдачи прав | S34–S35 |
| 17 | Диагностировать недоступную модель без утечки API key | S09, S12 |
| 18 | Экспортировать конфиг без секретов | S11 |
| 19 | Восстановить backup в отдельный тестовый каталог | S74 |
| 20 | Откатить adapter после регрессии | S43 |

Правило ADR-010 (если будет принят): этап, вводящий возможность, обязан добавить соответствующую строку таблицы, а не откладывать её в S75.

---

## 5. Backlog объёма работ, не привязанный к одному этапу

| Пункт | Причина отложения | Куда попадает |
|---|---|---|
| Автоматическое создание MCP для любой программы | §22 «Отложить» | после C14, оценка в APOCRYPHA |
| Свободное GUI-управление | §22, §10.1 | S63+ только с ограничениями |
| Большое количество субагентов | §11, §22 | S71 |
| Автономная перезапись identity/prompt | §12.3, §22 | не планируется без APOCRYPHA-эксперимента |
| Автоматическое принятие Instincts | §4.7, §22 | только через approval (S70) |
| Обязательная vector DB | §4.6, §22 | опционально, после C10 |
| Маркетплейс, multi-user, cloud sync | §22 | вне плана |
| Собственный генератор изображений | §22 | только адаптеры к provider/ComfyUI (S61+) |
| Сложная 3D-заставка | §22 | вне плана; Boot Ritual — S60 |

---

## 6. Что план явно НЕ предполагает

- Не предполагает, что все 22 подсистемы существуют до C8.
- Не предполагает, что UI нужен для работы ядра (S27 — вертикальный сценарий через CLI).
- Не предполагает, что векторный поиск, multi-agent и самообучение нужны для MVP.
- Не предполагает, что выбор стека сделан: ADR-001/002 имеют статус PENDING-PROTOTYPE.
- Не предполагает наличия кода ProjectMemory: ADR-017 ожидает ответа пользователя.

---

*Конец IMPLEMENTATION_PLAN.md S01.*
