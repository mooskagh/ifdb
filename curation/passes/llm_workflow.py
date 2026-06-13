from logging import getLogger
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

logger = getLogger("worker")


@register_pass
class LlmWorkflowPass(GameEditPass):
    name = "llm_workflow"

    def apply(self, state: GameEditState, params: dict[str, Any]) -> None:
        if state.approval in {Approval.REJECTED, Approval.CANCELLED}:
            return
        if is_noop_edit(state.current, state.served):
            return
        workflow = LlmWorkflow.objects.get(name=params["workflow"])
        logger.info(
            "Running LLM workflow %r for history #%s using runner %r and "
            "model %r",
            workflow.name,
            state.history.pk,
            workflow.runner,
            workflow.model.name,
        )
        try:
            runner_for_workflow(workflow, state).run()
        except Exception as e:
            logger.exception(
                "LLM workflow %r failed for history #%s using runner %r "
                "and model %r",
                workflow.name,
                state.history.pk,
                workflow.runner,
                workflow.model.name,
            )
            state.approval = Approval.PROPOSED
            state.needs_attention = True
            state.add_note(
                f'LLM workflow "{workflow.name}" failed: {e}; review logs.'
            )
            return
        logger.info(
            "LLM workflow %r completed for history #%s",
            workflow.name,
            state.history.pk,
        )
