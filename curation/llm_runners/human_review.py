from curation.edit import Approval
from curation.llm import register_llm_runner

from .base import GameEditStateLlmRunner


@register_llm_runner
class HumanReviewRunner(GameEditStateLlmRunner):
    runner_name = "human_review"

    def needs_human_review(self, reason: str) -> str:
        """Request human review for this edit."""
        self.state.approval = Approval.PROPOSED
        if reason and reason not in self.state.attention_reason:
            self.state.attention_reason.append(reason)
        return "human review requested"
