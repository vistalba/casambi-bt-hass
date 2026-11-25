# AGENTS.md

Guidelines for everyone (humans and AI agents) changing this repository. They
describe the standard changes are held to. [DEVELOPMENT.md](DEVELOPMENT.md)
covers the development setup and is not repeated here.

## Project overview

- `custom_components/casambi_bt/` is a Home Assistant custom integration
  (HACS) for Casambi lighting networks over Bluetooth LE.
- All Bluetooth and Casambi protocol handling lives in the library
  [casambi-bt](https://github.com/lkempf/casambi-bt) (`CasambiBt`). The
  integration pins an exact version in `manifest.json`.
- `CasambiApi` (`__init__.py`) owns the connection, reconnect logic and
  callbacks. Entities (`entities.py` and the platform modules) only read state
  from it and never talk to the library on their own.

## Branches and pull requests

- `main` is the release branch. Only `dev` is merged into `main`, which CI
  enforces (`branch_check.yaml`).
- Target `dev` with all changes. Work on a topic branch based on `dev`.
- One concern per pull request. Bug fixes, features and refactorings go into
  separate pull requests.
- Fix a problem where it originates. If the cause is in `casambi-bt`, fix it
  there (see [Library changes](#library-changes)). Add a workaround in the
  integration only if users need it before a library release, and comment it
  as such.

## Quality gates

Every change must pass all of these before it is pushed:

```bash
ruff check .
black . --check
pytest
```

- CI runs `ruff check` and `hassfest`. `black` and `pytest` are not run in CI
  yet, so run them locally.
- The test dependencies are listed in `requirements_test.txt`.
- Do not relax the configuration (`ruff.toml`, `pytest.ini`) to get a change
  through. Prefer a targeted `# noqa: <rule>` with a reason. File-wide
  `# ruff: noqa: SLF001` is accepted in tests that need private members.

## Code style

- Follow the existing structure, naming and typing. Ruff's rule set mirrors
  Home Assistant core (`ruff.toml`, Google-style docstrings).
- Keep `except (A, B):` parenthesized. The unparenthesized form only works on
  Python 3.14+ and black keeps the parentheses.
- Type all new functions. `cast()` is fine where the library is loosely
  typed, but don't silence real type errors.
- Code comments, docstrings, log messages and commit messages are in English.
- Keep changes minimal and focused. No drive-by refactorings, renames or
  formatting changes in unrelated code.

## Home Assistant practices

- **No blocking calls in the event loop.** File system access (e.g. the
  cache under `.storage/casambi_bt`) goes through
  `hass.async_add_executor_job`. Network and Bluetooth calls are always
  awaited.
- **Config entry lifecycle.** Raise the matching exception during setup:
  - `ConfigEntryNotReady` for transient Bluetooth problems,
  - `ConfigEntryAuthFailed` for rejected credentials (starts reauth),
  - `ConfigEntryError` only for permanent errors.

  Everything set up in `async_setup_entry` must be undone in
  `async_unload_entry`. Data stored outside the config entry is cleaned up in
  `async_remove_entry`.
- **Background tasks** are created with
  `entry.async_create_background_task`, so they are cancelled on unload. These
  tasks start eagerly (`eager_start=True`): the coroutine runs synchronously
  up to its first `await`, even inside a library callback. Never rely on state
  that the caller only updates after the callback returns.
- **Availability.** Entities are push-based (`should_poll = False`). Every
  change of the connection state must reach the entities through a callback,
  otherwise they show stale state. A disconnect has to make all dependent
  entities unavailable, and a reconnect must make them available again.
- **Config flow.** Map library errors to the existing error keys
  (`cannot_connect`, `invalid_auth`, `unknown`) and log the cause, so that
  users can report it. Every new user-facing string goes into `strings.json`
  and `translations/en.json`. Also update the other translations (`de.json`,
  `nl.json`) if you can translate reliably. Otherwise leave them unchanged.
- **Logging.**
  - `debug` for details,
  - `info` for rare state changes (connect, reconnect),
  - `warning` for problems that recover on their own,
  - `error` or `exception` only for problems that need user action.

  Never log passwords, session tokens or keys. Casambi network data may
  contain the owner's email address, so log it at `debug` level only.

## Bluetooth rules

- Get devices from Home Assistant: use
  `bluetooth.async_ble_device_from_address(hass, address, connectable=True)`.
  Never scan or create `BleakScanner` instances yourself. Connections go
  through `bleak-retry-connector` in the library.
- Expect every backend: local BlueZ adapters and ESPHome Bluetooth proxies
  behave differently. In particular:
  - Proxies raise a bare `TimeoutError` and word errors differently (e.g.
    `"<device> is not connected"`). Never match error messages, check the
    connection state instead.
  - Proxies have a limited number of connection slots. Always disconnect
    connections that are no longer needed, also after failed attempts.
- The disconnect callback is the only reliable signal for a lost link. There
  is no keep-alive, so code must not assume that `connected` is up to date
  while that callback is running.
- habluetooth drops advertisements that didn't change. An advertisement
  callback is therefore no reliable reconnect trigger. A reconnect started
  after a disconnect must keep retrying with backoff until it succeeds or the
  entry is unloaded. It must never stop silently, also not on unexpected
  errors.
- Changes to connection, reconnect or availability logic need a description of
  how they were tested. Say whether the test used real hardware (adapter or
  proxy model) or only mocks.

## Casambi specifics

- The library stores its cache per network under
  `.storage/casambi_bt/<address in lowercase, without colons>/`. Use
  `get_cache_uuid()` whenever this key is needed, never the raw address.
- A cached session skips the login, so the password is not verified while it
  is valid. Code that sets up a network anew (config flow, reauth) must start
  from an invalidated cache.

## Tests

- Every bug fix comes with a test that fails without the fix and passes with
  it. Check this before you push.
- Tests use `pytest-homeassistant-custom-component`. Mock Bluetooth and the
  Casambi cloud API, and never make real network or Bluetooth calls.
- Prefer real library objects with mocked transport over mocking the library
  API, when the bug depends on the library's behavior (e.g. the order of
  callbacks).
- Write files only to `tmp_path`, never into the shared test configuration
  directory.
- Keep tests independent of each other and of their order.

## Commits

- Write the subject in the imperative, at most about 72 characters, without
  a trailing period (e.g. `Fix cache invalidation in config flow`).
- The body explains why the change is needed and what was wrong, not only
  what changed.
- Reference issues with the full form, e.g.
  `Fixes lkempf/casambi-bt-hass#170`.
- Keep the original author when you take over someone else's commits
  (`git cherry-pick`), and don't squash them into your own.
- Each commit must pass the quality gates on its own.

## Library changes

Changes to `casambi-bt` follow its own checks:

```bash
ruff check .
black --check src tests
mypy .
pytest
```

- Don't add new `mypy` errors. Existing ones are not fixed in unrelated
  changes.
- Test library changes in the integration by installing the library from
  source (see [DEVELOPMENT.md](DEVELOPMENT.md)).
- The integration then pins the new release in `manifest.json`. Never pin a
  git URL or an unreleased version on `dev` or `main`.

## Reviewing pull requests

- Check the change against this document and run the quality gates on the
  merged result.
- For connection-related changes, check that:
  - no reconnect path can end without a retry,
  - state is updated before callbacks run,
  - every connection is closed on every error path,
  - unload cannot hang.
- Name the risks you found and describe what you tested.
