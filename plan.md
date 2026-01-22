# shadPS4 RetroArch Core + Sync + Test Tool Plan

## Decisions & Constraints
- **Branch strategy:** `main` contains local changes; nightly upstream sync merges into `main`.
- **Sync behavior:** auto-merge when clean; **open a PR** when conflicts exist.
- **Conflict resolution:** no official Copilot API for CI auto-resolution; use a **custom LLM-based PR bot** + tests (details below).
- **Target platforms:** all existing shadPS4 platforms.
- **UI:** disabled for the libretro core build.
- **Vulkan:** require **1.3+**.

---

## Workstream A — Nightly Upstream Sync (Option 3 + git rerere)

### A1) Nightly sync workflow
- Create `.github/workflows/upstream-sync.yml` (nightly + manual trigger).
- Workflow outline:
  1. Checkout `main` with full history (`fetch-depth: 0`).
  2. Add `upstream` remote and fetch `upstream/main`.
  3. Enable `git rerere`:
     - `git config rerere.enabled true`
     - `git config rerere.autoupdate true`
  4. Restore **rerere cache** (`.git/rr-cache`) via `actions/cache`.
  5. Attempt merge:
     - `git merge --no-ff --no-commit upstream/main`
     - If clean: commit + push to `main` (auto-merge path).
     - If conflicts: abort merge and create a **sync branch** that points to `upstream/main` (e.g., `sync/upstream-YYYYMMDD`), then open a PR into `main`.
  6. Save rerere cache for future runs.

### A2) Conflict resolution PR bot (LLM-based via Jules)
> **Note:** GitHub Copilot does not provide an official API to resolve conflicts in CI. Jules can create patches/PRs, but **merge still requires CI + approval gates**.
- Trigger: conflict PRs created by the sync workflow (label `auto-resolve`).
- Steps:
  1. Checkout PR branch and attempt merge into `main` to reproduce conflicts.
  2. Apply `git rerere` first (fast path for recurring conflicts).
  3. Start a Jules API session with:
     - repo URL + PR head SHA
     - conflict files/diff context
     - **system prompt** describing merge policy + shadPS4 constraints
  4. Pull Jules output (patch or branch) and apply to the PR branch.
  5. Run test suite(s).
  6. If tests pass: push changes to PR and optionally **auto-merge** via GitHub once required checks/approvals pass. If tests fail: leave PR for manual review.
- Security:
  - Store Jules API key as a GitHub secret.
  - Limit repo write access to trusted workflows only (avoid untrusted fork PRs).

---

## Workstream B — RetroArch Core Integration (Option 1)

### B1) Frontend abstraction layer
- Introduce a **frontend interface** to decouple window/input/audio from the emulator core.
- Keep existing SDL frontend as the default backend.
- Add a **libretro backend** that implements:
  - Input polling via libretro callbacks.
  - Audio output via `retro_audio_sample_batch`.
  - Timing and frame pacing suitable for RetroArch.

### B2) Libretro Vulkan backend (Vulkan 1.3+)
- Implement a libretro **Vulkan rendering path** using `libretro_vulkan.h`:
  - Use the frontend-provided Vulkan instance/device/interface.
  - Replace swapchain-dependent presentation with a **libretro presenter** that records and submits command buffers using the libretro Vulkan interface.
  - Ensure the presenter supports shadPS4’s Vulkan 1.3 requirement.
- Disable UI/ImGui/devtools for the libretro build via build flag(s).

### B3) Libretro core entry points
- Implement libretro API entry points for the core (init, run, load/unload, etc.).
- Provide a minimal libretro-facing configuration layer:
  - Paths, runtime settings, and safe defaults for core options.

### B4) Build targets + platform coverage
- Add a `LIBRETRO_CORE` build option and a new `shadps4_libretro` target.
- Ensure compatibility with **all existing shadPS4 platforms** by keeping SDL backend intact and isolating libretro changes behind build flags.

---

## Workstream C — UVX Python MCP Tool (RetroArch E2E Testing)

### C1) MCP SDK research & stdio server design
- Identify official MCP Python SDK/docs.
- If SDK exists: implement a **stdio MCP server** using it.
- If not: pause implementation and document how to proceed once SDK is confirmed.

### C2) Package layout + uvx execution
- Create a standalone Python tool under `tools/retroarch_mcp/` with its own `pyproject.toml`.
- Provide a console entrypoint (e.g., `retroarch-mcp`).
- Run via **uvx** (ephemeral tool execution):
  - `uvx --from ./tools/retroarch_mcp retroarch-mcp`

### C3) Core capabilities
- **RetroArch CLI launcher**
  - Launch RetroArch with core + content:
    - `retroarch -L <core> --config <cfg> --appendconfig <cfg> <content>`
- **Network control interface**
  - Send UDP commands (e.g., `QUIT`, `SCREENSHOT`, `PAUSE_TOGGLE`) to the configured port.
  - Enable with `network_cmd_enable = "true"` in config.
- **Artifacts**
  - Collect logs, screenshots, and save-states in a test output directory.

### C4) Visual validation with Gemini 3 Flash via OpenRouter
- For screenshot steps:
  1. Issue `SCREENSHOT` command.
  2. Load the image file.
  3. Send to Gemini 3 Flash with **expected UI element criteria** from test JSON.
  4. Record pass/fail and model rationale.
- Use `OPENROUTER_API_KEY` from /.env file (never commit secrets).

### C5) JSON test definition schema
- Support JSON-driven tests with steps like:
  - `launch`, `wait`, `input`, `command`, `screenshot_assert`, `save_state`, `load_state`, `exit`.
- Example fields:
  - `core_path`, `content_path`, `config_path`, `network_port`, `steps[]`.

### C6) Test runner behavior
- Execute steps sequentially; fail fast or collect all failures based on config.
- Emit machine-readable results (JSON) and human-readable summary.

---

## Deliverables
- `plan.md` (this document).
- Design specs for:
  - Nightly sync workflow + rerere caching.
  - LLM-based conflict resolution PR bot.
  - Libretro frontend + Vulkan presenter abstraction.
  - UVX MCP test tool architecture and JSON schema.

---

## Open Questions (to confirm during implementation)
- Location and availability of official MCP Python SDK.
- Exact RetroArch CLI flags required for screenshot output paths (may vary by platform/config).
- Test suite(s) to gate auto-merge after LLM conflict resolution.
