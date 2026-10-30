# Dual Sandbox Infrastructure (Local + Modal)

Two interchangeable backends behind one interface,
`backend.sandbox.SandboxRunner`:

| Method | Meaning |
| :--- | :--- |
| `create_or_attach(session_id, ...)` | Isolated workspace per PR/repair session |
| `start_dev_server()` | Persistent Next.js dev server (never restarted by a patch) |
| `apply_patch(unified_diff)` | Validate + apply diff in place, rollback on failure |
| `wait_for_hmr(patch_id)` | Compiler/HMR event for exactly that patch (stale-safe) |
| `get_status()` / `get_preview_url()` | Health, metrics, browser URL |
| `terminate()` | Stop server, clean up |

Patch phases are distinct states: `patch_applied` →
`compilation_succeeded` → `hmr_observed` → `visual_verified`.
Only Node 5 may set `visual_verified`.

## Local backend (verified now)

```bash
SANDBOX_BACKEND=local   # default; no credentials of any kind
```

- Workspaces live under `SANDBOX_LOCAL_ROOT` (default
  `/tmp/visorqa-sandboxes`), one directory per session.
- Git sources are cloned (`git clone --local` for local paths,
  branch/commit checked out); plain directories are copied with
  `node_modules` symlinked from the source when present.
- The dev server is a persistent subprocess on a free localhost port;
  stdout/stderr go to `dev-server.log` next to the checkout.
- Patches reuse Node 4's strict parser: traversal, protected
  `src/components/ui/*` (BR-2), unauthorized files, banned patterns,
  and stale context are rejected before any write; multi-file writes
  roll back on failure. Writes are serialized per sandbox.
- HMR is detected from compiler log events emitted after the patch's
  recorded log offset plus an HTTP health probe — never a fixed sleep.
  Timings (`patch_validation_ms`, `patch_apply_ms`,
  `hmr_propagation_ms`, `total_patch_to_hmr_ms`) are measured and
  reported honestly; ~300 ms is a warm-cache target, not a guarantee.
- `get_status()` detects crashes; `recover()` restarts the server with
  files intact. `terminate()` kills the process group and removes the
  workspace; `cleanup_expired()` removes idle sessions.

Run it:

```bash
.venv/bin/python -m pytest tests/unit/test_sandbox.py tests/integration/test_sandbox_next_hmr.py
```

## Modal backend (pending credentials)

Implemented against the official Modal SDK (verified locally against
modal 1.6.3: `App.lookup`, `Image.debian_slim`, `Sandbox.create(...,
encrypted_ports=, cpu=, memory=)`, `Sandbox.exec`, `Sandbox.tunnels()`).
It is **not live-tested**: no Modal account was available.

Activate it later:

```bash
SANDBOX_BACKEND=modal
MODAL_TOKEN_ID=<your token id>        # placeholders only - never commit real values
MODAL_TOKEN_SECRET=<your token secret>
MODAL_APP_NAME=visorqa-sandbox
pip install "modal>=1.0"   # already in backend/requirements.txt
```

Behavior guarantees:

- Importing the module and running the whole test suite require no
  Modal credentials and not even the SDK.
- Selecting `modal` without credentials raises an actionable
  `SandboxConfigError` naming the missing variables. It never falls
  back to local silently, and an invalid `SANDBOX_BACKEND` also errors.
- Patches are validated locally with the same strict rules, then the
  exact Unified Diff is applied inside the running container with
  `git apply --check && git apply`; the sandbox/dev server persist.
- The adapter accepts an injected SDK module (`modal_module=...`),
  which is how it is unit-tested without an account.

## Verification status

**Verified now:** local sandbox creation/reuse, persistent dev server
across sequential patches, real Next.js HMR (content-confirmed, same
PID), invalid/unauthorized/traversal/stale rejection, rollback,
concurrency serialization, HMR timeout/compile-failure/stale-event
handling, crash recovery, backend config/switching, Modal import and
credential-error behavior, Modal adapter logic via injected fake SDK,
Node 4 → sandbox → Node 5 state handoff, cleanup/limits.

**Pending credentials:** actual Modal authentication, sandbox
provisioning, in-container `npm`/`next dev` execution, tunnel preview
URLs, and live Modal HMR latency.
