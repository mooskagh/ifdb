from dataclasses import dataclass
from typing import Annotated, Literal

from curation.edit import Approval
from curation.llm import llm_tool, register_llm_runner

from .base import GameEditStateLlmRunner


@dataclass
class MatchParams:
    text_start: Annotated[
        str,
        "Existing body text at the start of the span to replace; not new "
        "text; must not be empty; around 5 words recommended",
    ]
    text_end: Annotated[
        str,
        "Existing body text at the end of the span to replace; included in "
        "the span; must not be empty unless to_end is true",
    ]
    occurrence: Annotated[
        int | None,
        "1-based occurrence; required only for non-unique text_start",
    ] = None
    to_end: Annotated[
        bool,
        "Set true only when the span must continue through the end of "
        "current_text; text_end must then be empty",
    ] = False


@dataclass
class DeleteExactParams:
    rationale: Annotated[str, "Explain why this exact text should be deleted"]
    text: Annotated[
        str,
        "Exact current_text substring to delete; must not be empty",
    ]
    occurrence: Annotated[
        int | None,
        "1-based occurrence; required for duplicate text; optional for "
        "unique text",
    ] = None


@dataclass
class ReplaceExactParams:
    rationale: Annotated[str, "Explain why this exact text should be replaced"]
    old: Annotated[
        str,
        "Exact current_text substring to replace; must not be empty",
    ]
    new: Annotated[str, "Exact replacement text"]
    occurrence: Annotated[
        int | None,
        "1-based occurrence; required for duplicate old text; optional for "
        "unique text",
    ] = None


@dataclass
class PatchParams:
    replace: Annotated[
        str,
        "Exact final text replacing the matched span; use an empty string to "
        "delete it",
    ]


@dataclass
class ReplacementParams:
    text: Annotated[
        str | None,
        "Exact text to insert; use an empty string to delete the matched span",
    ] = None
    clipboard_id: Annotated[
        str | None,
        "Clipboard id from a previous cut call to insert instead of text",
    ] = None


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
class ReplaceParams:
    rationale: Annotated[
        str,
        "Explain the decided replacement before selecting match/replacement; "
        "do not replace while uncertain",
    ]
    match: MatchParams
    replacement: ReplacementParams


@dataclass
class CutParams:
    rationale: Annotated[
        str,
        "Explain why this exact span should be cut before selecting match",
    ]
    match: MatchParams


@dataclass
class PasteParams:
    rationale: Annotated[
        str,
        "Explain why this text should be pasted at the selected position",
    ]
    position: Literal["start", "end", "before", "after"]
    text: Annotated[
        str | None,
        "Exact text to paste; provide exactly one of text or clipboard_id",
    ] = None
    clipboard_id: Annotated[
        str | None,
        "Clipboard id from a previous cut call; provide exactly one of text "
        "or clipboard_id",
    ] = None
    anchor: Annotated[
        str | None,
        "Existing current_text used for before/after insertion; forbidden for "
        "start/end",
    ] = None
    occurrence: Annotated[
        int | None,
        "1-based occurrence; required only for non-unique anchor",
    ] = None


@dataclass
class UndoParams:
    rationale: Annotated[str, "Explain why the previous edit should be undone"]


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
        self._clipboard: dict[str, str] = {}
        self._next_clipboard_id = 1
        self._undo_stack: list[str] = []
        self._successful_mutations = 0
        self._failed_mutations = 0

    def run(self):
        served_text = self.state.served.description or ""
        if not served_text.strip() and len(self.state.sources) <= 1:
            # self.state.add_note(
            #     "Fresh import from a single source, unlikely to have "
            #     "duplicates; skipping content editor"
            # )
            return None
        if not self._current_text().strip():
            # self.state.add_note(
            #     "Content editor skipped empty description body."
            # )
            return None
        trajectory = self.run_agent_loop(self.context(), require_tool=True)
        self._mark_attention_if_incomplete(trajectory)
        return trajectory

    @llm_tool
    def edit(self, params: EditParams) -> dict:
        """Replace exact text in the current game description body."""
        result = self.replace(
            ReplaceParams(
                rationale=params.rationale,
                match=params.match,
                replacement=ReplacementParams(text=params.edit.replace),
            )
        )
        if result["status"] == "replaced":
            result["status"] = "edited"
        elif result.get("error", "").startswith(
            "replacement produced no change"
        ):
            result["error"] = "edit produced no change"
        return result

    @llm_tool
    def delete_exact(self, params: DeleteExactParams) -> dict:
        """Delete an exact substring from the current game description body."""
        result = self.replace_exact(
            ReplaceExactParams(
                rationale=params.rationale,
                old=params.text,
                new="",
                occurrence=params.occurrence,
            )
        )
        if result["status"] == "replaced":
            result["status"] = "deleted"
        return result

    @llm_tool
    def replace_exact(self, params: ReplaceExactParams) -> dict:
        """Replace an exact substring in the current game description body."""
        text = self._current_text()
        try:
            start, end = _exact_span(
                text, params.old, params.occurrence, label="old"
            )
        except ValueError as e:
            return self._error(e)

        new_text = text[:start] + params.new + text[end:]
        if new_text == text:
            return self._error("replacement produced no change")
        if not new_text.strip():
            return self._error(
                "replacement would remove the entire current_text; choose a "
                "narrower exact text or request human review"
            )
        self._apply_text(new_text)
        return self._success("replaced", start, start + len(params.new))

    @llm_tool
    def replace(self, params: ReplaceParams) -> dict:
        """Replace exact text in the current game description body."""
        text = self._current_text()
        try:
            replacement = self._replacement_text(params.replacement)
            start, end = _match_span(text, params.match)
        except ValueError as e:
            return self._error(e)

        new_text = text[:start] + replacement + text[end:]
        if new_text == text:
            return self._error("replacement produced no change")
        if not new_text.strip():
            return self._error(
                "replacement would remove the entire current_text; choose a "
                "narrower span or request human review"
            )
        self._apply_text(new_text)
        return self._success("replaced", start, start + len(replacement))

    @llm_tool
    def cut(self, params: CutParams) -> dict:
        """Cut exact text from the current game description into clipboard."""
        text = self._current_text()
        try:
            start, end = _match_span(text, params.match)
        except ValueError as e:
            return self._error(e)
        if start == end:
            return self._error("cut produced no change")

        clipboard_id = self._new_clipboard_id()
        clipboard_text = text[start:end]
        self._clipboard[clipboard_id] = clipboard_text
        self._apply_text(text[:start] + text[end:])
        result = self._success("cut", start, start)
        result.update({
            "clipboard_id": clipboard_id,
            "clipboard_text": clipboard_text,
        })
        return result

    @llm_tool
    def paste(self, params: PasteParams) -> dict:
        """Paste exact text into the current game description body."""
        text = self._current_text()
        try:
            pasted = self._paste_text(params)
            index = _paste_index(text, params)
        except ValueError as e:
            return self._error(e)
        if not pasted:
            return self._error("paste text must not be empty")

        new_text = text[:index] + pasted + text[index:]
        self._apply_text(new_text)
        return self._success("pasted", index, index + len(pasted))

    @llm_tool
    def undo(self, params: UndoParams) -> dict:
        """Undo the most recent successful edit, cut, paste, or replace."""
        if not self._undo_stack:
            return self._error("nothing to undo")
        self.state.current.description = self._undo_stack.pop()
        self._successful_mutations += 1
        return self._success("undone", 0, 0)

    @llm_tool
    def finish(self, params: FinishParams) -> dict:
        """Finish editing with the selected resolution."""
        self._finished = True
        if params.resolution == "abort":
            self.state.current.description = self._original_text
            self.state.approval = Approval.REJECTED
            self.state.add_note(params.summary)
        elif (
            params.resolution == "commit"
            and self._failed_mutations
            and not self._successful_mutations
        ):
            self.state.approval = Approval.PROPOSED
            self.state.needs_attention = True
            self.state.add_note(
                "Content editor had failed edit attempts and made no changes: "
                f"{params.summary}"
            )
            return {
                "status": "finished",
                "resolution": "request_human_review",
                "summary": params.summary,
                "error": (
                    "commit rejected after failed edit attempts with no "
                    "successful mutation"
                ),
            }
        elif params.resolution == "request_human_review":
            self.state.approval = Approval.PROPOSED
            self.state.needs_attention = True
            self.state.add_note(params.summary)
        return {
            "status": "finished",
            "resolution": params.resolution,
            "summary": params.summary,
        }

    @llm_tool
    def complain(self, params: ComplainParams) -> dict:
        """Suggest improvements to this editing API."""
        note = f"Content editor complaint: {params.complaint}"
        if params.suggestion:
            note += f" Suggestion: {params.suggestion}"
        self.state.needs_attention = True
        self.state.add_note(note)
        return {"status": "complaint_recorded"}

    def should_stop(self, message, tool_results, step) -> bool:
        return self._finished

    def _current_text(self) -> str:
        return self.state.current.description or ""

    def _replacement_text(self, replacement: ReplacementParams) -> str:
        return self._one_text_source(
            replacement.text, replacement.clipboard_id
        )

    def _paste_text(self, params: PasteParams) -> str:
        return self._one_text_source(params.text, params.clipboard_id)

    def _one_text_source(
        self, text: str | None, clipboard_id: str | None
    ) -> str:
        if (text is None) == (clipboard_id is None):
            raise ValueError("provide exactly one of text or clipboard_id")
        if clipboard_id is None:
            return text or ""
        try:
            return self._clipboard[clipboard_id]
        except KeyError as e:
            raise ValueError(f"unknown clipboard_id {clipboard_id!r}") from e

    def _apply_text(self, new_text: str) -> None:
        self._undo_stack.append(self._current_text())
        self.state.current.description = new_text
        self._successful_mutations += 1

    def _new_clipboard_id(self) -> str:
        clipboard_id = f"clip_{self._next_clipboard_id}"
        self._next_clipboard_id += 1
        return clipboard_id

    def _success(self, status: str, start: int, end: int) -> dict:
        text = self._current_text()
        return {
            "status": status,
            "message": (
                "Operation applied to current_text. Inspect current_text; "
                "if it satisfies the task, call finish."
            ),
            "current_text": text,
            "snippet": _snippet(text, start, end),
        }

    def _error(self, error) -> dict:
        self._failed_mutations += 1
        return {
            "status": "error",
            "error": f"{error}; text is matched against current_text",
            "current_text": self._current_text(),
        }


def _paste_index(text: str, params: PasteParams) -> int:
    if params.position == "start":
        if params.anchor is not None or params.occurrence is not None:
            raise ValueError("anchor and occurrence are forbidden for start")
        return 0
    if params.position == "end":
        if params.anchor is not None or params.occurrence is not None:
            raise ValueError("anchor and occurrence are forbidden for end")
        return len(text)
    if params.anchor is None:
        raise ValueError("anchor is required for before/after")
    start, end = _anchor_span(text, params.anchor, params.occurrence)
    return start if params.position == "before" else end


def _anchor_span(
    text: str, anchor: str, occurrence: int | None
) -> tuple[int, int]:
    starts = _occurrences(text, anchor, label="anchor")
    if not starts:
        raise ValueError("anchor was not found")
    if len(starts) == 1 and occurrence is not None:
        raise ValueError("anchor is unique, so occurrence must be unset")
    if len(starts) > 1 and occurrence is None:
        raise ValueError(
            f"anchor was found {len(starts)} times; set 1-based occurrence"
        )
    if occurrence is None:
        start = starts[0]
    elif not 1 <= occurrence <= len(starts):
        raise ValueError(
            f"occurrence must be between 1 and {len(starts)} for this anchor"
        )
    else:
        start = starts[occurrence - 1]
    return start, start + len(anchor)


def _match_span(text: str, match: MatchParams) -> tuple[int, int]:
    starts = _occurrences(text, match.text_start, label="text_start")
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

    if match.to_end:
        if match.text_end:
            raise ValueError("text_end must be empty when to_end is true")
        end = len(text)
        _reject_repeated_start_inside_span(text, match, start, end)
        return start, end
    if not match.text_end:
        raise ValueError("text_end is required unless to_end is true")

    end = text.find(match.text_end, start)
    if end == -1:
        raise ValueError(
            "text_end was not found after the selected text_start"
        )
    end += len(match.text_end)
    _reject_repeated_start_inside_span(text, match, start, end)
    return start, end


def _exact_span(
    text: str, needle: str, occurrence: int | None, *, label: str
) -> tuple[int, int]:
    starts = _occurrences(text, needle, label=label)
    if not starts:
        raise ValueError(f"{label} was not found")
    if len(starts) > 1 and occurrence is None:
        raise ValueError(
            f"{label} was found {len(starts)} times; set 1-based occurrence"
        )
    if occurrence is None:
        start = starts[0]
    elif not 1 <= occurrence <= len(starts):
        raise ValueError(
            f"occurrence must be between 1 and {len(starts)} for this {label}"
        )
    else:
        start = starts[occurrence - 1]
    return start, start + len(needle)


def _reject_repeated_start_inside_span(
    text: str, match: MatchParams, start: int, end: int
) -> None:
    repeat = text.find(match.text_start, start + len(match.text_start), end)
    if repeat != -1:
        raise ValueError(
            "text_start appears again inside the matched span; choose a more "
            "specific text_start or a narrower span"
        )


def _occurrences(text: str, needle: str, *, label: str) -> list[int]:
    if not needle:
        raise ValueError(
            f"{label} must not be empty; choose existing text in current_text"
        )
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
