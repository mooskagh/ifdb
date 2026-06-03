"""Concrete edit passes, imported for registration side effects."""

from .dedup_personality_aliases import DedupPersonalityAliasesPass
from .enrichment import EnrichmentPass
from .llm_workflow import LlmWorkflowPass
from .merge_sources import MergeSourcesPass

__all__ = [
    "DedupPersonalityAliasesPass",
    "EnrichmentPass",
    "LlmWorkflowPass",
    "MergeSourcesPass",
]
