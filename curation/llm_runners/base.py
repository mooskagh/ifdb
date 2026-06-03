from dataclasses import asdict
from typing import Any

from curation.edit import GameEditState, SourceFetchInfo
from curation.gameinfo import GameInfo
from curation.llm import LlmWorkflowRunner


class GameEditStateLlmRunner(LlmWorkflowRunner):
    def run(self):
        return self.run_agent_loop(self.context())

    def context(self) -> dict[str, Any]:
        return game_edit_state_context(self.state)


def game_edit_state_context(state: GameEditState) -> dict[str, Any]:
    return {
        "history": {
            "id": state.history.id,
            "game_id": state.history.game_id,
            "state": state.history.state,
            "auto_updates": state.history.auto_updates,
            "attention_reason": state.history.attention_reason,
        },
        "approval": state.approval.name,
        "attention_reason": state.attention_reason,
        "served": game_info_context(state.served),
        "served_canonical_text": state.served.to_canonical(),
        "current": game_info_context(state.current),
        "current_canonical_text": state.current.to_canonical(),
        "last_applied": game_info_context(state.last_applied),
        "last_applied_canonical_text": state.last_applied.to_canonical(),
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
