from typing import Any

from curation.edit import (
    Approval,
    GameEditPass,
    GameEditState,
    is_noop_edit,
    register_pass,
)
from curation.llm import runner_for_workflow
from curation.models import LlmWorkflow


@register_pass
class LlmWorkflowPass(GameEditPass):
    name = "llm_workflow"

    def apply(self, state: GameEditState, params: dict[str, Any]) -> None:
        if state.approval in {Approval.REJECTED, Approval.CANCELLED}:
            return
        if is_noop_edit(state.current, state.served):
            return
        workflow = LlmWorkflow.objects.get(name=params["workflow"])
        try:
            runner_for_workflow(workflow, state).run()
        except Exception as e:
            state.approval = Approval.PROPOSED
            state.attention_reason.append(
                f'LLM workflow "{workflow.name}" failed: {e}; review logs.'
            )
