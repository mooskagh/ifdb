"""URL canonicalization pass for curation drafts."""

import re
from collections.abc import Callable
from typing import Any

from curation.edit import GameEditPass, GameEditState, register_pass
from games.gameinfo import GameInfo
from games.models import URL

RewriteRule = tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]

URL_REWRITES: list[RewriteRule] = [
    # Upgrade all HTTP URLs to HTTPS
    (re.compile(r"^http://"), "https://"),
    # instead-games.ru downloader -> download
    (
        re.compile(
            r"^https://(?:www\.)?instead-games\.ru/downloader\.php\?(?:.*&)?file=([^&#]+).*"
        ),
        r"https://instead-games.ru/download/\1",
    ),
]


@register_pass
class CanonicalizeUrlsPass(GameEditPass):  # type: ignore[misc]
    name = "canonicalize_urls"

    def apply(self, state: GameEditState, params: dict[str, Any]) -> None:
        canonicalize_urls(state.current)


def canonicalize_url(url: str) -> str:
    """Rewrite known non-canonical URL forms to their canonical counterpart."""
    if not url:
        return url
    url = url.strip()
    for pattern, repl in URL_REWRITES:
        url = pattern.sub(repl, url)
    return url


def canonicalize_urls(info: GameInfo) -> None:
    url_by_id = {
        u.id: u.original_url
        for u in URL.objects.filter(
            id__in={u.url_id for u in info.urls if u.url_id is not None}
        )
    }
    for entry in info.urls:
        raw_url = entry.url or url_by_id.get(entry.url_id)
        if not raw_url:
            continue
        canonical = canonicalize_url(raw_url)
        if canonical != raw_url:
            entry.url = canonical
            entry.url_id = None
