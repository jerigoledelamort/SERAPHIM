# SERAPHIM S02 Prototype — Stack Selection

**This is NOT production code.** It is an isolated prototype for stack evaluation only.

## What this is

A minimal prototype that validates the following stack requirements from the architecture spec:

- UI → backend round-trip (health response)
- Config read from test root
- File root confinement (path traversal blocked)
- Subprocess management (Windows Job Objects)
- No network exposure by default (127.0.0.1 only)
- Auth token required
- Reduced motion CSS

## Structure

```
stack-s02/
├── shared/testroot/      # Test root with config/health.yaml + index.html
├── backend-py/           # Python stdlib backend (server.py, procman.py)
├── backend-node/         # Node stdlib backend (server.cjs)
├── ui-electron/          # Electron shell (main.cjs, package.json)
├── ui-tauri/             # Tauri shell (build.rs, src/main.rs) — BUILD FAILED
├── harness/              # Test harness (test_backend.py, test_node.py)
├── results/              # Test results (backend-py.json)
└── logs/                 # Build/runtime logs (gitignored)
```

## How to run

```bash
# Python backend (all 24 tests)
cd backend-py
python server.py --root ../shared/testroot --config config/health.yaml --port-file .s02-port --token s02-test &
sleep 2
python ../harness/test_backend.py --port $(cat .s02-port) --root ../shared/testroot

# Node backend (smoke test)
cd backend-node
node server.cjs --root ../shared/testroot --config config/health.yaml --port-file .s02-port --token s02-test &
python ../harness/test_node.py

# Electron UI (manual)
cd ui-electron
npm install
npm start
```

## Removal plan

**To delete this prototype entirely:**

```bash
rm -rf prototypes/stack-s02/
```

This is safe because:
1. **No production code imports from `prototypes/`.** Production lives in `src/` (S03+).
2. **No dependencies on prototype files.** No package.json, Cargo.toml, or pyproject.toml outside this directory references anything here.
3. **Build artifacts are gitignored.** `node_modules/`, `target/`, `.venv/`, `__pycache__/`, `*.log` are all ignored.
4. **Test config is disposable.** `shared/testroot/config/health.yaml` contains no real values.

## Migration plan

Useful patterns from this prototype are documented in `ARCHITECTURE_DECISIONS.md` and carried into production (S03+) as follows:

| Pattern | Where it goes in production |
|---|---|
| Python backend server.py | Becomes the basis for `src/core/server.py` |
| Job Object subprocess (procman.py) | Becomes `src/sandbox/job_object.py` |
| Loopback HTTP + token auth | Becomes the standard API transport (ADR-003) |
| File root confinement | Becomes `src/aegis/filesystem.py` |
| Test harness pattern | Becomes `tests/` for S03+ |
| Electron main.cjs process spawn | Becomes `src/vessel/backend_launcher.ts` |
| Error envelope format | Becomes the standard API error contract |

## Key findings

1. **Tauri v2 BUILD FAILED in this environment** — `rc.exe` (Windows resource compiler) is required by `tauri-build` and was unavailable without MSVC Build Tools on Windows 11 Home. Tauri remains a possible future alternative, but Electron is the accepted VESSEL technology for the current implementation.
2. **Python backend: 24/24 tests PASS** — stdlib only, zero dependencies.
3. **Job Object isolation works** without admin rights on Windows 11 Home.
4. **Electron installs and runs** without admin and without MSVC.
5. **RTT 0.5ms** loopback (well under 50ms budget).

## Experimental versions (not production requirements)

- **Electron 33.2.0** — version used for the S02 prototype experiment. Production Electron version will be selected from a supported stable line when implementing the production VESSEL.
- **Python 3.10.10** — version used for the S02 prototype environment. Production Python runtime will use a supported version, fixed at S03+ in production configuration.

## S02 limitations (not proven in this experiment)

- Symlink confinement on Windows was **not tested** (Win11 Home without dev mode). Path traversal blocked ≠ complete filesystem confinement proven.
- Production packaging size was not measured.
- Electron auto-update was not tested.
- Tauri build with MSVC Build Tools installed was not tested (intentionally not installed).

The prototype does not need to be rewritten or migrated to newer versions; it already fulfilled its purpose of proving technology viability.
