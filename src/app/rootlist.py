"""Pure parsing helpers for Spotify's internal rootlist API (local-only).

The web player stores folders/playlist ordering in the rootlist at
``https://spclient.wg.spotify.com/playlist/v2/user/<username>/rootlist``.
``contents.items`` is a FLAT ordered list where each item has a ``uri``:

- Folder START: ``spotify:start-group:<16-hex-hash>:<urlencoded-name>``
- Folder END:   ``spotify:end-group:<hash>``
- Playlist:     ``spotify:playlist:<id>``

Everything between a start-group and its matching end-group belongs to that
folder; pairs nest. Empty-name start-groups are tracked on the open-hash
stack so their matching end-group pops correctly, but the ``("",)`` paths
they would contribute are excluded from the parsed output. This module only
contains pure functions so the parsing can be unit-tested without a browser.
"""

from __future__ import annotations

from urllib.parse import unquote_plus

_START_GROUP = "spotify:start-group:"
_END_GROUP = "spotify:end-group:"
_PLAYLIST = "spotify:playlist:"


def stable_start_group_uri(uri: str) -> str:
    """Return the stable folder reference ``spotify:start-group:<hash>``.

    Raw start-group item URIs carry a ``:<urlencoded-name>`` suffix; the stable
    reference used in MOV deltas (and returned by ``list_folders``) drops it.
    """
    if not uri.startswith(_START_GROUP):
        raise ValueError(f"not a start-group URI: {uri!r}")
    hash_ = uri[len(_START_GROUP) :].split(":", 1)[0]
    return f"{_START_GROUP}{hash_}"


def parse_rootlist_items(
    items: list[dict],
) -> tuple[dict[tuple[str, ...], str], dict[str, tuple[str, ...] | None]]:
    """Parse the flat rootlist ``contents.items`` list.

    Returns ``(folders, placements)``:

    - ``folders`` maps each folder path (a tuple of unquoted folder names, e.g.
      ``("My Shit", "Other's")``) -> its stable ``spotify:start-group:<hash>``
      URI. Empty-name folders are tracked for nesting but never appear in the
      returned paths.
    - ``placements`` maps each ``spotify:playlist:<id>`` -> the folder path it
      currently sits in (``None`` = library root). Empty-name folders are
      transparent, so a playlist inside one reports the enclosing named path.
    """
    folders: dict[tuple[str, ...], str] = {}
    placements: dict[str, tuple[str, ...] | None] = {}
    stack: list[str] = []  # unquoted names of the currently open groups
    for item in items:
        uri = item.get("uri") or ""
        if uri.startswith(_START_GROUP):
            rest = uri[len(_START_GROUP) :]
            _hash, _, name = rest.partition(":")
            # Names are URL-encoded with form-style encoding (`+` = space,
            # e.g. ``My+Shit`` -> ``My Shit``), hence ``unquote_plus``.
            name = unquote_plus(name)
            # Always track the group on the stack so its matching end-group
            # pops the right level (an empty name would otherwise make the
            # end-group pop the PARENT folder and corrupt nesting).
            stack.append(name)
            if not name:
                # Empty-name folders keep nesting correct but are excluded
                # from the returned folders/placements paths.
                continue
            folders[tuple(stack)] = stable_start_group_uri(uri)
        elif uri.startswith(_END_GROUP):
            if stack:
                stack.pop()
        elif uri.startswith(_PLAYLIST):
            path = tuple(name for name in stack if name)
            placements[uri] = path if path else None
    return folders, placements
