"""Merge fetched source canonicals into a draft ``GameInfo``."""

from curation.edit import GameEditPass, GameEditState, register_pass
from curation.gameinfo import GameInfo, merge, parse
from curation.models import GameSource

# Source priority mirrors the old importers' ``priority`` values
# (games/importer/*.py); higher wins first. Sources without an explicit
# priority (current text, rilarhiv) fall back to ``_DEFAULT_PRIORITY``.
_DEFAULT_PRIORITY = -1000
_SOURCE_PRIORITY = {
    GameSource.SourceType.STICKY_NOTE: 1000,
    GameSource.SourceType.IFWIKI: 100,
    GameSource.SourceType.INSTEAD: 80,
    GameSource.SourceType.QUESTBOOK: 51,
    GameSource.SourceType.PLUT: 50,
    GameSource.SourceType.APERO: 49,
    GameSource.SourceType.IFICTION: 45,
    GameSource.SourceType.QSP: 40,
}


@register_pass
class MergeSourcesPass(GameEditPass):
    name = "merge_sources"

    def apply(self, state: GameEditState, params: dict) -> None:
        usable = sorted(
            (s for s in state.sources if s.canonical_text),
            key=lambda s: _SOURCE_PRIORITY.get(s.type, _DEFAULT_PRIORITY),
            reverse=True,
        )
        if not usable:  # nothing to merge -> keep served draft
            return
        merged = GameInfo()
        for s in usable:  # highest priority first -> first-wins
            merged = merge(merged, parse(s.canonical_text))
        state.current = merged
