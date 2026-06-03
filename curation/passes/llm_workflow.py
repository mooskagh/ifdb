from typing import Any

from curation.edit import GameEditPass, GameEditState, register_pass
from curation.llm import runner_for_workflow
from curation.models import LlmWorkflow


@register_pass
class LlmWorkflowPass(GameEditPass):
    name = "llm_workflow"

    def apply(self, state: GameEditState, params: dict[str, Any]) -> None:
        workflow = LlmWorkflow.objects.get(name=params["workflow"])
        runner_for_workflow(workflow, state).run()
