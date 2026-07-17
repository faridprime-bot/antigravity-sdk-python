# CLAUDE.md

Guidance for AI assistants (Claude Code and similar) working in this
repository.

## What this repo is

`google-antigravity` is Google's Python SDK for building AI agents powered by
Antigravity and Gemini. It wraps a compiled Go "local harness" binary behind
an async Python API, so callers focus on agent behavior (tools, hooks,
policies, triggers) instead of the wire protocol to the backend.

This repository is exported from Google's internal source-of-truth via
Copybara — expect Google-internal conventions (Apache license headers,
2-space indentation, Google-style docstrings) even though the repo lives on
GitHub. **Do not add external-contribution scaffolding** (e.g. contributor
license agreements, "good first issue" tooling); `CONTRIBUTING.md` states this
project does not accept external contributions.

Cloning the repo does **not** give you a runnable SDK: the platform-specific
compiled binary (`google/antigravity/bin/localharness`) is only present in
wheels published to PyPI. If you need to actually run an agent end-to-end
(not just import/lint/unit-test the Python), install from PyPI
(`pip install google-antigravity`) rather than relying on an editable install
of this checkout alone.

## Architecture: three layers

The SDK is deliberately layered; know which layer owns which concern before
changing code so you don't leak responsibilities across layers.

| Layer | Package | Owns | Key classes |
|---|---|---|---|
| 1 — Simplified | `google/antigravity/agent.py` | Declarative setup: config, hooks, triggers, policies, MCP bridges, tool runner wiring | `Agent` |
| 2 — Session | `google/antigravity/conversation/` | Session state: step history, turn tracking, compaction indices, usage | `Conversation`, `ChatResponse`, `Step`, `ToolCall` |
| 3 — Adapter | `google/antigravity/connections/` | Transport plumbing: wire protocol, process lifecycle, idle/wakeup | `Connection`, `ConnectionStrategy`, `LocalConnection` |

Most users only touch `Agent`. `Conversation` is for callers who need
history/usage introspection or step-level streaming. `Connection` is the
transport abstraction — today only `LocalConnection` (WebSocket + protobuf to
the Go harness) is implemented; new backends get their own sub-package under
`connections/` (see "Package-per-strategy" below).

Hooks and triggers are independent, complementary systems — don't conflate
them:
- **Hooks** (`google/antigravity/hooks/`) intercept the agent's own lifecycle
  (pre/post tool call, pre/post turn, errors, interactions). Inline,
  blocking, can approve/deny/transform.
- **Triggers** (`google/antigravity/triggers/`) react to external events
  (cron, file changes, webhooks) and push messages into an agent from the
  background. Async, can only call `ctx.send(...)`.

Two independent state systems exist and intentionally do **not** share
state: `HookContext` (hierarchical, per session/turn/operation, used by
hooks) and `ToolContext` (flat, session-scoped, used by tools).

## Directory map

```
google/antigravity/
├── agent.py                 # Layer 1: Agent
├── types.py                 # Canonical Pydantic v2 boundary types (Step, ToolCall, Content, ...)
├── models.py                 # Model/endpoint config types (ModelConfig, GeminiAPIEndpoint, ThinkingLevel, ...)
├── connections/
│   ├── connection.py          # ABCs: Connection, ConnectionStrategy, AgentConfig
│   └── local/                 # LocalConnection strategy (WebSocket + protobuf to Go harness)
├── conversation/
│   └── conversation.py        # Layer 2: Conversation, ChatResponse
├── hooks/
│   ├── hooks.py                # Hook base classes (Inspect / Decide / Transform taxonomy)
│   ├── hook_runner.py          # HookRunner: dispatch + TOCTOU-safe ordering
│   └── policy.py               # Declarative policy DSL (deny/allow/ask_user/enforce)
├── policy/                    # Thin re-export facade over hooks/policy.py (see below)
├── tools/
│   ├── tool_runner.py          # ToolRunner: registry + execution of Python/MCP tools
│   └── tool_context.py         # ToolContext: per-conversation tool state
├── triggers/
│   ├── triggers.py             # TriggerContext, @trigger decorator
│   ├── trigger_runner.py       # TriggerRunner lifecycle
│   └── helpers.py              # every(), on_file_change() factories
└── utils/
    └── interactive.py          # run_interactive_loop() + interactive CLI hooks

examples/
├── getting_started/           # One feature per file, runnable standalone
└── deep_dives/                 # Multi-feature realistic mini-applications

skills/google-antigravity-sdk/  # Packaged skill (SKILL.md + references/) for
                                 # agent tools that consume this SDK via the
                                 # Vercel/Context7 skills CLIs — keep in sync
                                 # with actual SDK behavior when it changes.
```

Every package under `google/antigravity/` that has meaningful public surface
carries its own `README.md` (`connections/README.md`, `hooks/README.md`,
`tools/README.md`, `triggers/README.md`, `conversation/README.md`). **Read the
relevant package README before making non-trivial changes there** — they
document design decisions (e.g. hook execution ordering, disabling vs.
denying tools) that aren't obvious from the code alone. Update those READMEs
in the same change if you alter the behavior they describe.

## Conventions

- **License headers**: every `.py` file starts with the Apache 2.0 boilerplate
  header (`Copyright 2026 Google LLC ...`). Copy it verbatim into new files.
- **Indentation**: 2 spaces, Google Python style (not the more common 4-space
  PEP 8 style) — match the surrounding file.
- **Imports**: one symbol per `from ... import X` line, alphabetized; no
  wildcard imports. `__init__.py` files re-export the public API explicitly
  and mirror the export list in `__all__`.
- **Tests**: colocated as `<module>_test.py` next to the module they test
  (not in a separate `tests/` tree), using `unittest` (often
  `unittest.IsolatedAsyncioTestCase` for async code) with `unittest.mock`.
- **Types**: `google/antigravity/types.py` is the canonical Pydantic v2
  boundary — pure Python, no proto dependencies. Proto bindings only exist
  inside a connection strategy's own sub-package (e.g.
  `connections/local/localharness_pb2.py`) and must not leak into `types.py`
  or other layer-1/2 code.
- **`policy/` vs `hooks/policy.py`**: `google/antigravity/hooks/policy.py` has
  the actual policy DSL implementation; `google/antigravity/policy/__init__.py`
  is a re-export-only facade. Add new policy behavior to `hooks/policy.py`,
  then re-export it from `policy/__init__.py` if it's public API.
- **Package-per-strategy**: a new `ConnectionStrategy` gets its own
  sub-package under `connections/` co-locating impl, config, proto bindings,
  and tests (see `connections/README.md`). Don't add a second strategy's code
  into `connections/local/`.
- **Docstrings**: Google-style `Args:`/`Returns:` sections on public methods
  (see `agent.py`).

## Working with tools, hooks, and policies

- Prefer `CapabilitiesConfig.enabled_tools` / `disabled_tools` to remove a
  tool from the model's context entirely (no token cost, tool never
  considered). Use `policy.deny()` only when the restriction is conditional
  on arguments or needs the model to see *why* it was refused (costs tokens
  on rejected calls). Don't reach for both to solve the same problem.
- Any config that enables write tools or MCP servers **must** also set
  `policies=[...]` (or a `pre_tool_call_decide_hook`) — `Agent.__aenter__`
  raises `ValueError` otherwise. If you're writing an example or test with
  write tools enabled, include an explicit policy (e.g.
  `policy.allow_all()` for a sandboxed test) rather than working around the
  check.
- Policy evaluation is priority-ordered (specific-deny > specific-ask >
  specific-allow > wildcard-deny > wildcard-ask > wildcard-allow), first
  match wins within a level. Predicate exceptions fail closed (treated as a
  match). Keep this in mind when reordering or adding policies.

## Development workflow

```bash
# Install in editable mode with dev/test deps
pip install -e ".[dev]"

# Run the full unit test suite
python -m pytest -v --tb=short

# Run tests for one package
python -m pytest google/antigravity/hooks/

# Build the wheel (won't contain the compiled harness binary locally)
python -m build --wheel --outdir dist/
```

- There is no separate lint/format config checked in (no `ruff`/`black`/
  `pylintrc`); match the existing 2-space Google style by hand or by mirroring
  a nearby file.
- `.kokoro/presubmit.sh` (also used for continuous builds) is the source of
  truth for CI: sets up Python 3.10, installs hashed deps from
  `.kokoro/requirements-test.txt`, runs `pytest`, builds the wheel, then
  reinstalls it and sanity-imports `Agent` and `LocalConnection`. If you
  change `pyproject.toml` dependencies, the lockfiles under `.kokoro/` need
  regenerating via `pip-compile` (see comments in `presubmit.sh`) — this repo
  doesn't do it automatically.
- `.github/workflows/run_examples.yml` runs every file in
  `examples/getting_started/` (except the interactive one) against a real
  `GEMINI_API_KEY` on tag pushes, as an end-to-end smoke test. If you add a
  new getting-started example, make sure it can run non-interactively to
  completion (or add it to the skip list alongside `human_in_the_loop.py`).
- This is a Kokoro (Google-internal CI) + GitHub Actions dual setup — the
  `.kokoro/*.cfg`/`*.sh` files are the real gate; GitHub Actions only covers
  the example smoke test.

## Adding examples

- `examples/getting_started/`: one file, one concept, runnable standalone
  with just `GEMINI_API_KEY` set. Add a matching entry to
  `examples/getting_started/README.md`.
- `examples/deep_dives/`: multi-concept mini-applications. Add a matching row
  to the table in `examples/deep_dives/README.md` (and the top-level
  `examples/README.md` table if it's a new deep dive).
- `skills/google-antigravity-sdk/examples/` mirrors select getting-started
  examples as skill reference docs — update these alongside the example if
  the referenced behavior changes.

## Gotchas

- `Agent.__init__` deep-copies the incoming `config` but keeps the *original*
  `config.hooks`/`config.triggers` list objects (see the comment in
  `agent.py`) so that hook/trigger instances retain reference identity for
  callers holding onto them — don't "simplify" this by copying config as a
  whole and reusing `self._config.hooks`.
- `TriggerRunner` assumes one connection per agent session; don't share a
  connection across multiple agents.
- Built-in tool results reaching `PostToolCallHook` are pre-summarized per
  tool (e.g. `grep_search` gives a match *count*, not the matches) — see the
  table in `hooks/README.md` before assuming a hook can see full built-in
  tool output.
