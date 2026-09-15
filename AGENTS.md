# AGENTS.md

Spotify playlist generator. Python 3.12, `src/` layout, package `app`.

## Commands (Windows / PowerShell)

- Use `uv` for everything — it manages the project venv, deps, and lockfile (Python 3.12 pinned via `.python-version`).
- PowerShell 5.1 has no `&&`; chain with `;` and `if ($?) { ... }`.
- Install/resync deps: `uv sync` (after editing `pyproject.toml` or `uv add <pkg>`); regenerates `uv.lock`.
- Lint: `uv run ruff check src tests`
- Format: `uv run ruff format src tests` (config: line-length 100, select `E,F,I,UP,B`)
- Test: `uv run pytest -q`
- Run: `uv run python -m app <subcommand>` → `auth | import <path> | poll | recent [N] | sync-genres | sync-albums`; flags `--dry-run`, `--top N`.

## Storage

- Production DB is **Neon Postgres** via `psycopg`. Local dev/tests use **SQLite**. Selected by the `DATABASE_URL` scheme (`postgresql://` vs `sqlite:///path` or `:memory:`).
- Do **not** add `libsql-experimental`/Turso — it does not build on Windows (Rust/maturin). Postgres is the chosen cloud store.
- `listens` table: unique key `(played_at, track_uri)`; upserts use `ON CONFLICT DO NOTHING` (idempotent). `create_schema` is `IF NOT EXISTS` and runs on every `_open_db()` call (reads included).
- db tests run against SQLite (`sqlite:///:memory:`) only — never a live Postgres or Spotify.

## Auth

- PKCE flow uses `spotipy.oauth2.SpotifyPKCE`, **not** `SpotifyOAuth` (the latter requires a `client_secret`).
- Two modes: interactive `auth` (browser, caches `.tokens.json`) and headless `poll`/`_get_spotify` (uses `SPOTIFY_REFRESH_TOKEN`).
- Secrets come from `.env` (gitignored). Never commit `.env`, `.tokens.json`, or the Client ID.

## Data sources / workflows

- Listening history: (1) continuous `poll` reading `recently-played` (rolling last 50), (2) one-time `import <zip|dir>` from the Spotify data export. The real export is `my_spotify_data(3).zip` in the repo root (personal data — gitignored).
- CI: `.github/workflows/poll.yml` cron `*/15 * * * *`; requires GitHub secrets `SPOTIFY_CLIENT_ID`, `SPOTIFY_REFRESH_TOKEN`, `DATABASE_URL`.
- Playlist generation: `sync-genres` (multi-genre via artist genres), `sync-albums` (recently-listened albums grouped by date-range windows via `app.albums.group_albums_by_window`). Both create fresh timestamped playlists; `--dry-run` writes nothing to Spotify.

## Subagents (opencode)

- `project-planner` (planning, read-only), `build-worker` (implementation), `code-reviewer` (lint/test/review). Defined in `.opencode/agent/`.
- Workflow rule: route planning → `project-planner`, implementation/edits → `build-worker`, review + test/lint verification → `code-reviewer`. The primary agent does not write project code directly.
