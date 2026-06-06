from dataclasses import dataclass
from typing import Annotated

from curation.edit import Approval
from curation.llm import llm_tool, register_llm_runner

from .base import GameEditStateLlmRunner


@dataclass
class NeedsHumanReviewParams:
    reason: Annotated[str, "Why this edit needs human review"]


@register_llm_runner
class HumanReviewRunner(GameEditStateLlmRunner):
    runner_name = "human_review"

    @llm_tool
    def needs_human_review(self, params: NeedsHumanReviewParams) -> dict:
        """Request human review for this edit."""
        self.state.approval = Approval.PROPOSED
        self.state.needs_attention = True
        self.state.add_note(params.reason)
        return {"status": "human_review_requested"}

    def should_stop(self, message, tool_results, step) -> bool:
        return self.state.approval == Approval.PROPOSED or super().should_stop(
            message, tool_results, step
        )
