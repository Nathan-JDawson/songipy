# Songipy — Spotify Playlist Generator

Automatically generate Spotify playlists from your own library and listening history, and organize them into real folders on your account.

The project uses your **saved library** (for genre playlists), your **listening history** (imported from a Spotify data export and continuously polled), and Spotify's **internal rootlist API** (for real playlist folders that the public Web API can't create).

## Features

- **Genre playlists** (`sync-genres`) — your saved tracks grouped by their artists' genres, one timestamped playlist per genre (only genres with ≥ 50 songs).
- **Date-range album playlists** (`sync-albums`) — every album you've recently listened to, grouped into playlists by time window: `Last 7 Days`, `Last 30 Days`, `Days 8-14`, `Last 90 Days`. Albums play back-to-back, most-recent first.
- **Listening history** — one-time `import` of your Spotify data export, plus a continuous `poll` that records new plays every few minutes (cloud cron in CI).
- **Real folders** (`organize`) — files all `Songipy/…` playlists into real Spotify folders using the web player's internal API (local-only).
- **Folder-style naming** — all generated playlists are named `Songipy/Albums/…` and `Songipy/Genres/…` so they group together even before `organize` is run.
- **Rate-limit safe** — automatic `429` retry with `Retry-After` backoff on every Spotify API call.

## Requirements

- **Python 3.12** (managed by `uv`, pinned in `.python-version`)
- **[uv](https://docs.astral.sh/uv/)** for dependencies, the venv, and the lockfile
- A **Spotify for Developers** app (Client ID + a redirect URI of `http://127.0.0.1:8080/callback`)
- **Storage**: a Postgres URL (e.g. Neon) in production; plain SQLite for local dev/tests
- **Optional, for `organize`**: Playwright + a dedicated Chrome/Chromium profile logged into open.spotify.com

## Setup

```powershell
# 1. Install dependencies (creates .venv + uv.lock)
uv sync

# 2. Configure the environment
Copy-Item .env.example .env
# edit .env — set SPOTIFY_CLIENT_ID, SPOTIFY_REFRESH_TOKEN (after step 3), DATABASE_URL

# 3. Log in once to mint a refresh token (opens a browser)
uv run python -m app auth

# 4. Import your Spotify data export (a .zip or extracted folder of Streaming_History_*.json)
uv run python -m app import "path\to\MyData.zip"
```

`.env` is gitignored. Never commit it, `.tokens.json`, or the Client ID.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `SPOTIFY_CLIENT_ID` | Spotify app Client ID | — |
| `SPOTIFY_REDIRECT_URI` | OAuth redirect (must match the app's registered URI) | `http://127.0.0.1:8080/callback` |
| `SPOTIFY_REFRESH_TOKEN` | Long-lived token for headless/cloud use | — |
| `SPOTIFY_TOKEN_CACHE` | Where the interactive token is cached | `.tokens.json` |
| `DATABASE_URL` | `postgresql://…` (prod) or `sqlite:///path` / `sqlite:///:memory:` (dev) | — |
| `SPOTIFY_CHROME_PROFILE` | Dedicated browser profile dir for `organize` | `.spotify-chrome-profile/` |
| `SPOTIFY_CHROME_CHANNEL` | Installed browser for `organize` (`chrome`, `msedge`); unset = bundled Chromium | *(unset)* |
| `SPOTIFY_USERNAME` | Account username override for `organize` (else derived from `spotify.me()`) | — |
| `FOLDER_SYNC_HEADLESS` | `1` to run the `organize` browser headless | `0` |

## Usage

```powershell
uv run python -m app <command> [--dry-run] [--top N]
```

| Command | Description |
|---|---|
| `auth` | Interactive login; caches the token in `.tokens.json` |
| `import <path>` | Import a Spotify data export (zip or directory) into the listens DB |
| `poll` | Fetch recent plays and store new ones (used by CI, runnable locally) |
| `recent [N]` | Print the last N listens from the DB (default 10) |
| `sync-genres` | Create per-genre playlists from saved tracks |
| `sync-albums` | Create per-date-window album playlists from recent listens |
| `organize` | Move `Songipy/…` playlists into real Spotify folders |

Global flags:

- `--dry-run` — compute and print what would happen without writing to Spotify (for `organize`, no browser is launched; playlists are still read via the Web API).
- `--top N` — limit saved tracks (`sync-genres`) or albums per window (`sync-albums`).

### Typical flow

```powershell
uv run python -m app import my_spotify_data.zip      # once, with your export
uv run python -m app sync-genres --dry-run           # preview
uv run python -m app sync-genres                     # create genre playlists
uv run python -m app sync-albums --dry-run
uv run python -m app sync-albums                     # create album playlists
uv run python -m app organize --dry-run
uv run python -m app organize                        # file them into real folders
```

## How playlists are generated

- **Genres**: tracks are tagged with every genre of their artists (`artists` endpoint, batched 50/call). A playlist is created per genre, but only if it would hold ≥ `MIN_PLAYLIST_TRACKS` (50) tracks.
- **Albums**: listens in the DB are grouped into time windows defined by `ALBUM_WINDOWS` in `src/app/config.py` (last 7/30/90 days and the 8–14-day-ago week). An album counts as "listened to" if ≥ `MIN_TRACKS_PER_ALBUM` (3) distinct tracks were played in the window. Each window becomes one playlist with the albums' full track lists back-to-back, ordered by most-recent activity.
- **Names**: `Songipy/Albums/<window> — <UTC timestamp>` and `Songipy/Genres/<genre> — <UTC timestamp>` (`PLAYLIST_ROOT` is configurable; set it to `""` to disable the prefix). A fresh timestamped playlist is created on every run — nothing is overwritten.

## Real folders (`organize`, local-only)

The public Spotify Web API has **no folder support**, so `organize` drives the web player's **internal rootlist API** (`https://spclient.wg.spotify.com/playlist/v2/user/<username>/rootlist`), which the Spotify web app itself uses. It launches a browser, captures the session headers from a single intercepted request, then reads/writes the folder tree via `fetch`.

- **Layout is flat**: creates `Songipy Albums` and `Songipy Genres` and moves the matching `Songipy/…` playlists into them. (Nested `Songipy → Albums/Genres` is a future enhancement.)
- **Idempotent**: already-created folders and already-placed playlists are skipped; re-running is a no-op.
- **Auth**: requires a dedicated logged-in profile (`SPOTIFY_CHROME_PROFILE`; default `.spotify-chrome-profile/`). Log in once manually. Bundled Chromium by default; use `SPOTIFY_CHROME_CHANNEL` for an installed browser.
- **Dry-run is browser-free**: `organize --dry-run` lists the plan using Web API data only.
- **Local-only**: it needs an interactive browser session, so it must **never** be added to the GitHub Actions poll workflow.

> Note: automating the web player's internal API is unofficial and subject to Spotify's terms. Keep usage low-volume and personal.

## Continuous polling (CI)

`.github/workflows/poll.yml` runs `python -m app poll` on a `*/15 * * * *` cron (plus `workflow_dispatch`). It requires GitHub repository secrets:

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_REFRESH_TOKEN`
- `DATABASE_URL`

The poller writes new plays into the DB so `sync-albums` always reflects your current listening without re-importing.

## Development

```powershell
uv run ruff check src tests        # lint
uv run ruff format src tests       # format
uv run pytest -q                   # tests (SQLite only — never a live Postgres/Spotify)
```

- Dependencies: edit `pyproject.toml` / `uv add <pkg>`, then `uv sync`.
- Tests run against `sqlite:///:memory:`; the Postgres path is covered by the live `organize`/import flows, not unit tests.
- Subagents (opencode): `project-planner` (planning), `build-worker` (implementation), `code-reviewer` (review + lint/test). See `AGENTS.md`.

## Project layout

```
src/app/
  __main__.py      # CLI (auth, import, poll, recent, sync-genres, sync-albums, organize)
  auth.py          # PKCE + refresh-token auth
  db.py            # Postgres/SQLite storage layer (listens table)
  import_history.py# Spotify export parser
  poll.py          # recently-played poller
  library.py       # saved tracks / album track pagination
  classify.py      # artist genres -> per-genre track lists
  albums.py        # recent-albums grouping by date windows
  folder_plan.py   # playlist-name -> folder mapping (pure)
  rootlist.py      # internal rootlist response parser (pure)
  folders.py       # Playwright driver for the internal rootlist API
  api.py           # rate-limit (429) retry helper
tests/             # pytest suite (SQLite only)
.github/workflows/poll.yml
```

## Keeping this README current

Update `README.md` in the **same commit** as any change to commands, environment variables, behavior, or setup steps. `AGENTS.md` carries the same rule for future agent sessions.