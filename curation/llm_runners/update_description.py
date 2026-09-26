from typing import Any

from curation.edit import GameEditState
from curation.llm import register_llm_runner
from curation.passes.merge_sources import build_description_delta

from .content_editor import ContentEditorRunner, ReadonlyFile


@register_llm_runner
class UpdateDescriptionRunner(ContentEditorRunner):
    runner_name = "update_description"

    def __init__(
        self, workflow: Any, state: GameEditState, **params: Any
    ) -> None:
        delta = build_description_delta(state.sources)
        state.source_snapshots = {"old": delta.old_ids, "new": delta.new_ids}
        self._has_delta = delta.old != delta.new
        super().__init__(
            workflow,
            state,
            **params,
            readonly_files=[
                ReadonlyFile("sources_old", delta.old),
                ReadonlyFile("sources_new", delta.new),
                ReadonlyFile("sources_diff", delta.diff),
            ],
        )

    def run(self) -> Any:
        if not self._has_delta:
            return None
        return super().run()
