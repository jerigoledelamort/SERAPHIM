# CORE offline CLI vertical slice

Все команды ниже выполняются из корня репозитория в Git Bash. Используется только FakeProvider; script — ограниченный JSON, не Python-код. UI, сеть и live-provider не нужны.

## Автоматическая проверка

```bash
.venv/Scripts/python.exe -m pytest backend/tests/e2e -q
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check backend/
```

E2E harness запрещает socket.connect/create_connection как в pytest, так и в CLI subprocess. Это test guard, не OS network sandbox. Golden проверяет реальные байты, независимый filesystem.read evidence, events и чтение persisted success новым процессом. Negative tests: policy deny, malformed call, provider timeout, repeated unchanged calls, path escape, unavailable verifier, pause/resume/cancel и approval после restart.

## Ручной golden

Выберите **новую пустую** временную директорию вне репозитория. DB root и sandbox должны быть раздельными, не вложенными друг в друга. Не используйте рабочие данные. В родительской директории создайте `outside.txt` с известными байтами и сохраните его hash для последующего сравнения.

Создайте `plan.json`:

```json
[{"text":"{\"goal\":\"write file\",\"steps\":[{\"id\":\"write\",\"title\":\"write file\",\"verification\":[\"file_exists\"],\"expected_outputs\":[\"a.txt\"],\"risk_hint\":\"write\"}]}"}]
```

Создайте `run.json`:

```json
[{"tool_calls":[{"id":"write-1","name":"tool.fs.write_file","arguments":{"path":"a.txt","text":"verified bytes"}}]},{"text":"done"}]
```

Подставьте свои абсолютные пути вместо `/c/Temp/seraphim-demo`:

```bash
export PYTHONPATH=backend
.venv/Scripts/python.exe -m seraphim.cli.main task --root /c/Temp/seraphim-demo/runtime --sandbox /c/Temp/seraphim-demo/sandbox --script /c/Temp/seraphim-demo/plan.json create 'write file'
# Скопируйте task_id из JSON ответа:
.venv/Scripts/python.exe -m seraphim.cli.main task --root /c/Temp/seraphim-demo/runtime --sandbox /c/Temp/seraphim-demo/sandbox --script /c/Temp/seraphim-demo/run.json run TASK_ID
.venv/Scripts/python.exe -m seraphim.cli.main task --root /c/Temp/seraphim-demo/runtime --sandbox /c/Temp/seraphim-demo/sandbox show TASK_ID
.venv/Scripts/python.exe -m seraphim.cli.main task --root /c/Temp/seraphim-demo/runtime --sandbox /c/Temp/seraphim-demo/sandbox report TASK_ID
.venv/Scripts/python.exe -m seraphim.cli.main task --root /c/Temp/seraphim-demo/runtime --sandbox /c/Temp/seraphim-demo/sandbox events TASK_ID
```

Ожидается `SUCCEEDED`, sandbox/a.txt содержит точно `verified bytes`, report содержит source `filesystem.read`, observed_at и evidence_ref, events — ToolCallStarted/ToolCallCompleted/VerificationResult. Пересчитайте hash outside.txt: он должен совпасть. Проверяйте не только stdout модели.

## JSON и exit codes

Успешные команды возвращают JSON. `run`: 0 только для SUCCEEDED, 1 для остановки/approval/block/failure. Click usage error — 2. Другие mutations возвращают persisted record; inspect — recovery checkpoint, report — runs/evidence. Ошибки runtime/service возвращают JSON error с type/code и exit 1 без raw exception message. Click usage errors остаются стандартным текстом и exit 2.

`--policy deny` отказывает, `--policy ask` требует точного approval. После run с NEEDS_APPROVAL получите approval ID из `inspect`, затем вызовите `approve TASK_ID APPROVAL_ID` с отдельным script `[ {"text":"done"} ]`. `deny` использует те же ID. Пауза и resume не снимают review и не разблокируют терминальный BLOCKED.

## Границы гарантий

- CORE контролирует lifecycle; модель не определяет passing evidence или SUCCEEDED.
- Checks плана и snapshots manifests не удаляются моделью. Mutable built-in filesystem postconditions компонуются по порядку операций; directory moves не имеют recursive content inventory.
- Missing mandatory verifier блокирует; optional unavailable виден в report. App-state/screenshot без реального адаптера unavailable.
- Неизвестный эффект, open intent, stale owner, interrupted accounting требуют review. Автоматического owner stealing/replay нет. Safe ready cursor допускает explicit resume; VERIFYING повторяет observation, а не action.
- Thread timeout ограничивает ожидание, не уничтожает произвольный worker. Cancel не rollback. Late effect возможен; после unknown новые действия не разрешены. В CLI не включён произвольный process tool.
- Cwd не OS sandbox; ADR-005/015/016 остаются открытыми. Существующая local DB содержит bounded raw transcript/arguments/results: не помещайте secrets в scripts.
- До live-provider нужны production isolation, privacy/transmission controls, credential-safe diagnostics, настоящие adapters/verifiers и расширенная concurrency/fault matrix. Этот сценарий не объявляет их готовыми.


## Corrective checkpoint verification (2026-11-12)

Authority-negative CLI scenario starts in sandbox A, persists a pending approval,
restarts against the same database with sandbox B and rejects approval with
`TASK_INVALID` before consumption or accounting. The subprocess harness disables
socket connections; both sandbox paths remain unwritten and outside sentinel
bytes remain unchanged. Unchanged-root restart still executes normally.

Actual standalone CLI observation (not only pytest): a new temporary workspace
ran create/run to persisted `SUCCEEDED`, with `filesystem.read`, consumed accepted
step evidence and actual bytes `observed bytes`. A second task stopped at
`NEEDS_APPROVAL`; changed-root approve returned exit 1 with
`{"error":{"code":"TASK_INVALID","type":"SeraphimError"}}`. Direct persisted
inspection showed approval `PENDING`, empty `consumed_at`, unchanged accounting,
no destination file in sandbox B and outside bytes `unchanged`.
Observation workspace: `C:/Users/egork/AppData/Local/Temp/seraphim-authority-observe-hgewmtjq`.
Runtime observation also exposed a usability limitation: `inspect` now includes
large nested authority snapshots; output is correct but verbose. CLI generic safe
errors expose code/type rather than an operator-friendly authority explanation.

Compatibility: existing plain step criteria (and JSON criteria without scope)
are checked at their step and retained as accepted authoritative historical
proof. JSON `{"kind":"file_content","target":"a.txt","expected":"one","scope":"final"}`
additionally requires `one` at task finish. Only built-in mutable filesystem
postconditions compose by canonical identity; manifest and arbitrary plan checks
are not silently dropped. Final output corruption still fails verification.

Diagnostic reports, including persisted empty/subset/optional checks, cannot
advance managed tasks. Regression coverage also tampers revision/history,
expected/mandatory/call_id/evidence/outcomes, target, consumption and cancellation;
two same-revision authoritative runs permit only one transition. Verification's
filesystem root must match durable authority.

Migration 0007 is append-only; v6 runtime rows gain a durable managed marker but
not invented authority or eligible runs. Legacy approvals/runs require review,
not automatic replay. Historical terminal records are not rewritten/reverified.

Remaining limits: no production OS sandbox, worker termination/rollback, live
provider readiness, recursive directory inventory or exhaustive concurrency/fault
matrix is claimed. Arbitrary third-party provider configuration requires an
explicit authority adapter; current built-ins bind root/executable allowlist and
full manifests. Whole-registry binding intentionally rejects unrelated tool drift.


Initial corrective verification commands/results (before two additional self-review regression tests):
- `.venv/Scripts/python.exe -m pytest backend/tests/core backend/tests/wings backend/tests/test_storage_migrations.py -q` — **406 passed / 2 skipped** (46.37s).
- `.venv/Scripts/python.exe -m pytest backend/tests/e2e -q` — **14 passed** (14.84s), including network-disabled changed-root approval restart negative.
- `.venv/Scripts/python.exe -m pytest backend/tests/core/test_authority_regressions.py -q` — **23 passed** (14.92s).
- `.venv/Scripts/python.exe -m ruff check backend/` — **PASS**.
- `git diff --check` — **PASS** (existing LF/CRLF normalization warnings only).
Skips remain host limitations: privileged filesystem symlinks (filesystem and storage path tests) and Windows directory write-permission bits. No new semantic skip was introduced. Independent reviewer verdict is not claimed by these implementation results.

### Final self-review rerun, without subagents
- Full pytest: **1469 passed / 3 skipped** (90.08s).
- Authority regressions plus verification: **40 passed** (19.60s), including rejection of a complete diagnostic report and provider replacement during policy evaluation not changing the validated invocation.
- Offline CLI E2E: **14 passed** (14.90s); CORE/WINGS/migrations: **406 passed / 2 skipped** (41.97s), run before the last two tests, which passed in the full suite.
- Explicit filesystem skip check: **67 passed / 3 skipped** (0.34s). Ruff and diff whitespace checks passed.
- All commands use `.venv/Scripts/python.exe`; exact commands are recorded in IMPLEMENTATION_LOG.md. An initial new-test fixture error (malformed ID) was fixed and rerun, not hidden as a product failure.

Verdict: **READY TO COMMIT**, limited to the offline S24–S27 implementation. This is a self-review, not an independent audit; no commit/push or following stage was executed. Manual follow-up: review the intended changed/untracked file list before staging, exclude the preserved root test-output artifacts unless deliberately wanted, and run privileged symlink/POSIX permission checks on a suitable host if those guarantees are required.
