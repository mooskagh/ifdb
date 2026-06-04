from dataclasses import dataclass
from typing import Annotated, Literal

from curation.edit import Approval
from curation.llm import llm_tool, register_llm_runner

from .base import GameEditStateLlmRunner


@dataclass
class MatchParams:
    text_start: Annotated[
        str,
        "Existing body text at the start of the span to replace; not new text",
    ]
    text_end: Annotated[
        str,
        "Existing body text at the end of the span to replace; included in "
        "the span",
    ]
    occurrence: Annotated[
        int | None,
        "1-based occurrence; required only for non-unique text_start",
    ] = None


@dataclass
class PatchParams:
    replace: Annotated[
        str,
        "Exact final text replacing the matched span; use an empty string to "
        "delete it",
    ]


@dataclass
class EditParams:
    rationale: Annotated[
        str,
        "Explain the decided edit before selecting match/replace; do not edit "
        "while uncertain",
    ]
    match: MatchParams
    edit: PatchParams


@dataclass
class FinishParams:
    summary: Annotated[str, "Brief summary of the editing outcome"]
    resolution: Literal["abort", "commit", "request_human_review"]


@dataclass
class ComplainParams:
    complaint: Annotated[
        str,
        "What editing API functionality is missing or awkward",
    ]
    suggestion: Annotated[
        str | None,
        "Suggested better API shape or behavior",
    ] = None


@register_llm_runner
class ContentEditorRunner(GameEditStateLlmRunner):
    runner_name = "content_editor"

    def __init__(self, workflow, state, **params):
        super().__init__(workflow, state, **params)
        self._original_text = state.current.description or ""
        self._finished = False

    def run(self):
        trajectory = self.run_agent_loop(self.context(), require_tool=True)
        self._mark_attention_if_incomplete(trajectory)
        return trajectory

    @llm_tool
    def edit(self, params: EditParams) -> dict:
        """Replace exact text in the current game description body."""
        try:
            new_text, edit_start, edit_end = self._edited_text(params)
        except ValueError as e:
            return {"status": "error", "error": str(e)}
        self.state.current.description = new_text

        return {
            "status": "edited",
            "snippet": _snippet(new_text, edit_start, edit_end),
        }

    @llm_tool
    def finish(self, params: FinishParams) -> dict:
        """Finish editing with the selected resolution."""
        self._finished = True
        if params.resolution == "abort":
            self.state.current.description = self._original_text
            self.state.approval = Approval.CANCELLED
        elif params.resolution == "request_human_review":
            self.state.approval = Approval.PROPOSED
            if (
                params.summary
                and params.summary not in self.state.attention_reason
            ):
                self.state.attention_reason.append(params.summary)
        return {
            "status": "finished",
            "resolution": params.resolution,
            "summary": params.summary,
        }

    @llm_tool
    def complain(self, params: ComplainParams) -> dict:
        """Suggest improvements to this editing API."""
        return {"status": "complaint_recorded"}

    def should_stop(self, message, tool_results, step) -> bool:
        return self._finished

    def _edited_text(self, params: EditParams) -> tuple[str, int, int]:
        text = self.state.current.description or ""
        start, end = _match_span(text, params.match)
        new_text = text[:start] + params.edit.replace + text[end:]
        return new_text, start, start + len(params.edit.replace)


def _match_span(text: str, match: MatchParams) -> tuple[int, int]:
    starts = _occurrences(text, match.text_start)
    if not starts:
        raise ValueError("text_start was not found")
    if len(starts) == 1 and match.occurrence is not None:
        raise ValueError("text_start is unique, so occurrence must be unset")
    if len(starts) > 1 and match.occurrence is None:
        raise ValueError(
            f"text_start was found {len(starts)} times; set 1-based occurrence"
        )
    if match.occurrence is None:
        start = starts[0]
    elif not 1 <= match.occurrence <= len(starts):
        raise ValueError(
            "occurrence must be between "
            f"1 and {len(starts)} for this text_start"
        )
    else:
        start = starts[match.occurrence - 1]

    end = text.find(match.text_end, start)
    if end == -1:
        raise ValueError(
            "text_end was not found after the selected text_start"
        )
    return start, end + len(match.text_end)


def _occurrences(text: str, needle: str) -> list[int]:
    if not needle:
        raise ValueError("text_start must not be empty")
    starts = []
    start = 0
    while True:
        found = text.find(needle, start)
        if found == -1:
            return starts
        starts.append(found)
        start = found + len(needle)


def _snippet(text: str, start: int, end: int) -> str:
    before = max(0, start - 200)
    after = min(len(text), end + 200)
    line_start = text.rfind("\n", 0, before)
    line_end = text.find("\n", after)
    return text[
        0 if line_start == -1 else line_start + 1 : len(text)
        if line_end == -1
        else line_end
    ]
