from dataclasses import asdict
from typing import Any

from curation.edit import Approval, GameEditState, SourceFetchInfo
from curation.gameinfo import GameInfo
from curation.llm import LlmWorkflowRunner


class GameEditStateLlmRunner(LlmWorkflowRunner):
    def run(self):
        trajectory = self.run_agent_loop(self.context())
        self._mark_attention_if_incomplete(trajectory)
        return trajectory

    def _mark_attention_if_incomplete(self, trajectory):
        if self.stop_reason == "max_error_tool_calls":
            self.state.approval = Approval.REJECTED
            self.state.needs_attention = True
            self.state.add_note(
                f'LLM workflow "{self.workflow.name}" stopped after too many '
                f"failed tool calls; review trajectory #{trajectory.pk}."
            )
        elif self.stop_reason == "missing_tool_calls":
            self.state.approval = Approval.REJECTED
            self.state.needs_attention = True
            self.state.add_note(
                f'LLM workflow "{self.workflow.name}" stopped without using '
                f"tools; review trajectory #{trajectory.pk}."
            )

    def context(self) -> dict[str, Any]:
        return game_edit_state_context(self.state)


def game_edit_state_context(state: GameEditState) -> dict[str, Any]:
    return {
        "history": {
            "id": state.history.id,
            "game_id": state.history.game_id,
            "state": state.history.state,
            "auto_updates": state.history.auto_updates,
            "note": state.history.note,
        },
        "approval": state.approval.name,
        "notes": state.notes,
        "needs_attention": state.needs_attention,
        "served": game_info_context(state.served),
        "served_canonical_text": state.served.to_canonical(),
        "served_content_text": state.served.description or "",
        "current": game_info_context(state.current),
        "current_canonical_text": state.current.to_canonical(),
        "current_content_text": state.current.description or "",
        "last_applied": game_info_context(state.last_applied),
        "last_applied_canonical_text": state.last_applied.to_canonical(),
        "last_applied_content_text": state.last_applied.description or "",
        "sources": [source_context(source) for source in state.sources],
    }


def game_info_context(info: GameInfo) -> dict[str, Any]:
    return asdict(info)


def source_context(source: SourceFetchInfo) -> dict[str, Any]:
    return {
        "url": source.url,
        "type": source.type,
        "raw_content": source.raw_content,
        "canonical_text": source.canonical_text,
        "previous_raw_content": source.previous_raw_content,
        "previous_canonical_text": source.previous_canonical_text,
        "status": source.status.name,
        "fetch_id": source.fetch.id if source.fetch else None,
    }
