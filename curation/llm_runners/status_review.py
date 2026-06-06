from dataclasses import dataclass
from typing import Annotated, Literal

from curation.edit import Approval
from curation.llm import llm_tool, register_llm_runner

from .base import GameEditStateLlmRunner


@dataclass
class SetStatusParams:
    rationale: Annotated[str, "Why this status is correct for the edited data"]
    status: Literal["accept", "needs_human_review"]


@register_llm_runner
class StatusReviewRunner(GameEditStateLlmRunner):
    runner_name = "status_review"

    def __init__(self, workflow, state, **params):
        super().__init__(workflow, state, **params)
        self._finished = False

    def run(self):
        if self.state.approval is not Approval.APPLIED:
            return None
        served_text = self.state.served.description or ""
        if not served_text.strip():
            return None
        current_text = self.state.current.description or ""
        if current_text.strip() == served_text.strip():
            return None
        trajectory = self.run_agent_loop(self.context(), require_tool=True)
        self._mark_attention_if_incomplete(trajectory)
        return trajectory

    @llm_tool
    def set_status(self, params: SetStatusParams) -> dict:
        """Set whether the edited data can be accepted or needs review."""
        self._finished = True
        if params.status == "accept":
            self.state.approval = Approval.APPLIED
            self.state.needs_attention = False
        else:
            self.state.approval = Approval.PROPOSED
            self.state.needs_attention = True
            self.state.add_note(f"Review needed: {params.rationale}")
        return {"status": "set", "approval": self.state.approval.name}

    def should_stop(self, message, tool_results, step) -> bool:
        return self._finished
