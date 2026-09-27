"""Concrete edit passes, imported for registration side effects."""

from .canonicalize_urls import CanonicalizeUrlsPass
from .cleanup_text import CleanupTextPass
from .dedup_personality_aliases import DedupPersonalityAliasesPass
from .enrichment import EnrichmentPass
from .llm_workflow import LlmWorkflowPass
from .merge_sources import MergeSourcesPass

__all__ = [
    "CanonicalizeUrlsPass",
    "DedupPersonalityAliasesPass",
    "CleanupTextPass",
    "EnrichmentPass",
    "LlmWorkflowPass",
    "MergeSourcesPass",
]
