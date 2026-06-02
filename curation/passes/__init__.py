"""Concrete edit passes, imported for registration side effects."""

from .dedup_personality_aliases import DedupPersonalityAliasesPass
from .enrichment import EnrichmentPass
from .merge_sources import MergeSourcesPass

__all__ = [
    "DedupPersonalityAliasesPass",
    "EnrichmentPass",
    "MergeSourcesPass",
]
