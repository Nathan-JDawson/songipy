# AGENTS.md

Spotify playlist generator. Python 3.12, `src/` layout, package `app`.

## Commands (Windows / PowerShell)

- Use `uv` for everything — it manages the project venv, deps, and lockfile (Python 3.12 pinned via `.python-version`).
- PowerShell 5.1 has no `&&`; chain with `;` and `if ($?) { ... }`.
- Install/resync deps: `uv sync` (after editing `pyproject.toml` or `uv add <pkg>`); regenerates `uv.lock`.
- Lint: `uv run ruff check src tests`
- Format: `uv run ruff format src tests` (config: line-length 100, select `E,F,I,UP,B`)
- Test: `uv run pytest -q`
- Run: `uv run python -m app <subcommand>` → `auth | import <path> | poll | recent [N] | sync-genres | sync-albums | organize`; flags `--dry-run`, `--top N`.

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

## Folder sync (local only)

- Command: `uv run python -m app organize --dry-run` (prints the plan using only Web API data — no browser launched) / `uv run python -m app organize` (launches the Spotify web player with Playwright to create real folders and move `Songipy/` playlists into them).
- `organize` talks to Spotify's **internal rootlist API** (host `https://spclient.wg.spotify.com`, path `/playlist/v2/user/<username>/rootlist`) instead of DOM scraping. It launches the logged-in profile, loads open.spotify.com, intercepts ONE `api-partner.spotify.com/pathfinder` request to capture the `authorization` / `client-token` / `spotify-app-version` / `app-platform` headers, then makes every spclient call from the page context via `fetch`. Reads use `GET /rootlist?decorate=revision,length,attributes,timestamp,owner,capabilities`; writes use `POST /rootlist/changes` with `ADD` (create folder) and `MOV` (move playlist) deltas. Folder start URIs are `spotify:start-group:<16-hex-hash>:<urlencoded-name>` (stable reference `spotify:start-group:<hash>`), end URIs `spotify:end-group:<hash>`; `contents.items` is a flat ordered list. The pure parsing lives in `app/rootlist.py` (unit-tested); the browser driver lives in `app/folders.py` (not unit-tested).
- The driver defaults to Playwright's **bundled Chromium** (no `channel`). To use an installed browser instead, set `SPOTIFY_CHROME_CHANNEL` (e.g. `chrome` or `msedge`). Note: Google Chrome is not currently installed on this machine, so `SPOTIFY_CHROME_CHANNEL=chrome` will fail with a "distribution 'chrome' is not found" error; leave it unset (bundled Chromium) or use `msedge`. It requires a dedicated logged-in profile: set `SPOTIFY_CHROME_PROFILE` (defaults to the gitignored `.spotify-chrome-profile/` under the repo root; log in once manually). Run `uv add playwright` once (already in `[project].dependencies`).
- Headful by default; opt into headless with `FOLDER_SYNC_HEADLESS=1`. The layout is **flat**: `organize` creates up to two top-level folders — `Songipy Albums` and `Songipy Genres` — and moves each `Songipy/Albums/...` playlist into `Songipy Albums` and each `Songipy/Genres/...` playlist into `Songipy Genres`. Playlist names keep their `Songipy/...` prefix. The account username for the spclient URLs comes from `SPOTIFY_USERNAME` (optional override) or is derived from `spotify.me()["id"]` before the browser opens.
- **LOCAL-ONLY**: must NOT be added to the GitHub Actions poll workflow (it requires an interactive Chrome session and a logged-in profile).

## Subagents (opencode)

- `project-planner` (planning, read-only), `build-worker` (implementation), `code-reviewer` (lint/test/review). Defined in `.opencode/agent/`.
- Workflow rule: route planning → `project-planner`, implementation/edits → `build-worker`, review + test/lint verification → `code-reviewer`. The primary agent does not write project code directly.
- **README rule**: update `README.md` in the same commit as any change to commands, env vars, behavior, or setup steps — the README must stay current.
