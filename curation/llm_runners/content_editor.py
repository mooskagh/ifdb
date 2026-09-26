from dataclasses import dataclass
from typing import Annotated, Any, Literal

from curation.edit import Approval
from curation.llm import llm_tool, register_llm_runner

from .base import GameEditStateLlmRunner


@dataclass
class SourceRef:
    file: Annotated[str, "Name of a configured readonly file (not current)"]
    start_line: Annotated[int, "First source line, 1-based and inclusive"]
    end_line: Annotated[int, "Last source line, 1-based and inclusive"]


@dataclass
class ReplaceLinesParams:
    start_line: Annotated[int, "First current line, 1-based and inclusive"]
    end_line: Annotated[int, "Last current line, 1-based and inclusive"]
    rationale: Annotated[str, "Explain the decided edit"]
    text: Annotated[
        str | None, "Literal replacement; empty string deletes lines"
    ] = None
    source: Annotated[
        SourceRef | None,
        "Readonly source; with text use file='', start_line=0, end_line=0",
    ] = None


@dataclass
class InsertLinesParams:
    line: Annotated[int, "Current line; for an empty file use line 1, before"]
    position: Annotated[Literal["before", "after"], "Insert relative to line"]
    rationale: Annotated[str, "Explain the decided insertion"]
    text: Annotated[str | None, "Literal lines to insert"] = None
    source: Annotated[
        SourceRef | None,
        "Readonly source; with text use file='', start_line=0, end_line=0",
    ] = None


@dataclass
class ReplaceTextParams:
    start_line: Annotated[int, "First current line, 1-based and inclusive"]
    end_line: Annotated[int, "Last current line, 1-based and inclusive"]
    old: Annotated[str, "Nonempty, unique substring within the selected lines"]
    new: Annotated[str, "Literal replacement text"]
    rationale: Annotated[str, "Explain the decided edit"]


@dataclass
class UndoParams:
    rationale: Annotated[str, "Explain why the previous edit should be undone"]


@dataclass
class FinishParams:
    resolution: Annotated[
        Literal["commit", "abort", "request_human_review"], "Final disposition"
    ]
    summary: Annotated[str, "Brief summary of the editing outcome"]


@dataclass
class ComplainParams:
    complaint: Annotated[
        str, "What editing API functionality is missing or awkward"
    ]
    suggestion: Annotated[
        str | None, "Suggested better API shape or behavior"
    ] = None


@dataclass
class ReadonlyFile:
    name: str
    text: str


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _range(text: str, start_line: int, end_line: int) -> tuple[int, int]:
    lines = _lines(text)
    if not 1 <= start_line <= end_line <= len(lines):
        raise ValueError(
            f"invalid line range {start_line}-{end_line}; use 1-{len(lines)}"
        )
    return sum(map(len, lines[: start_line - 1])), sum(
        map(len, lines[:end_line])
    )


def _terminated(text: str) -> bool:
    return text.endswith(("\n", "\r"))


def _separator(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _splice(original: str, start: int, end: int, inserted: str) -> str:
    before, after = original[:start], original[end:]
    separator = _separator(original)
    if inserted:
        if before and not _terminated(before):
            before += separator
        if after and not _terminated(inserted):
            inserted += separator
        elif not after and _terminated(original) and not _terminated(inserted):
            inserted += (
                original[-2:] if original.endswith("\r\n") else original[-1]
            )
    elif not after and before and not _terminated(original):
        before = before.removesuffix("\r\n").removesuffix("\n")
    return before + inserted + after


def _display(name: str, text: str, *, editable: bool) -> str:
    header = f"FILE: {name} [{'editable' if editable else 'readonly'}]"
    return "\n".join([
        header,
        *(
            f"{i}: {line.removesuffix(chr(10)).removesuffix(chr(13))}"
            for i, line in enumerate(_lines(text), 1)
        ),
    ])


@register_llm_runner
class ContentEditorRunner(GameEditStateLlmRunner):
    runner_name = "content_editor"

    def __init__(self, workflow: Any, state: Any, **params: Any) -> None:
        super().__init__(workflow, state, **params)
        self._original_text: str = state.current.description or ""
        self._finished = False
        self._undo_stack: list[str] = []
        self._successful_mutations = 0
        self._failed_mutations = 0
        files: list[ReadonlyFile | dict[str, str]] = params.get(
            "readonly_files", []
        )
        self._readonly_files: dict[str, str] = {}
        for item in files:
            name, text = (
                (item.name, item.text)
                if isinstance(item, ReadonlyFile)
                else (item["name"], item["text"])
            )
            if not name or name == "current" or name in self._readonly_files:
                raise ValueError(
                    f"duplicate or reserved readonly file name: {name!r}"
                )
            self._readonly_files[name] = text

    def context(self) -> dict[str, Any]:
        context = super().context()
        current = _display("current", self._current_text(), editable=True)
        files = [
            current,
            *(
                _display(name, text, editable=False)
                for name, text in self._readonly_files.items()
            ),
        ]
        context["numbered_files"] = "\n\n".join(files)
        context["current_file"] = current
        return context

    def run(self) -> Any:
        served_text = self.state.served.description or ""
        if (
            not served_text.strip()
            and len(self.state.sources) <= 1
            and not self._readonly_files
        ):
            return None
        if not self._current_text().strip() and not self._readonly_files:
            return None
        trajectory = self.run_agent_loop(self.context(), require_tool=True)
        self._mark_attention_if_incomplete(trajectory)
        return trajectory

    @llm_tool
    def replace_lines(self, params: ReplaceLinesParams) -> dict[str, Any]:
        """Replace inclusive current lines; empty text deletes them all."""
        current = self._current_text()
        try:
            start, end = _range(current, params.start_line, params.end_line)
            replacement = self._content(params.text, params.source)
        except ValueError as error:
            return self._error(error)
        result = _splice(current, start, end, replacement)
        if result == current:
            return self._error("replacement produced no change")
        self._apply_text(result)
        return self._success("replaced")

    @llm_tool
    def insert_lines(self, params: InsertLinesParams) -> dict[str, Any]:
        """Insert relative to a line; in an empty file use before line 1.

        Insertion after the last line appends.
        """
        current = self._current_text()
        try:
            count = len(_lines(current))
            if not count and params.line == 1 and params.position == "before":
                offset = 0
            elif 1 <= params.line <= count and params.position in (
                "before",
                "after",
            ):
                offset = sum(
                    map(
                        len,
                        _lines(current)[
                            : params.line - (params.position == "before")
                        ],
                    )
                )
            else:
                raise ValueError(
                    f"invalid insertion position; use lines 1-{count} "
                    "or before line 1 for an empty file"
                )
            inserted = self._content(params.text, params.source)
        except ValueError as error:
            return self._error(error)
        result = _splice(current, offset, offset, inserted)
        if result == current:
            return self._error("insertion produced no change")
        self._apply_text(result)
        return self._success("inserted")

    @llm_tool
    def replace_text(self, params: ReplaceTextParams) -> dict[str, Any]:
        """Replace unique nonempty text within inclusive current lines."""
        current = self._current_text()
        try:
            start, end = _range(current, params.start_line, params.end_line)
            if not params.old:
                raise ValueError("old must not be empty")
            bounded = current[start:end]
            first = bounded.find(params.old)
            if first < 0 or bounded.find(params.old, first + 1) >= 0:
                raise ValueError(
                    "old must occur exactly once within the selected lines; "
                    "narrow the range or use longer old text"
                )
        except ValueError as error:
            return self._error(error)
        result = (
            current[:start]
            + current[start:end].replace(params.old, params.new, 1)
            + current[end:]
        )
        if result == current:
            return self._error("replacement produced no change")
        self._apply_text(result)
        return self._success("replaced")

    @llm_tool
    def undo(self, params: UndoParams) -> dict[str, Any]:
        """Undo the most recent successful mutation."""
        if not self._undo_stack:
            return self._error("nothing to undo")
        self.state.current.description = self._undo_stack.pop()
        self._successful_mutations += 1
        return self._success("undone")

    @llm_tool
    def finish(self, params: FinishParams) -> dict[str, Any]:
        """Finish: commit, restore original (abort), or request review."""
        if params.resolution == "commit":
            if self._failed_mutations and not self._successful_mutations:
                self.state.approval = Approval.PROPOSED
                self.state.needs_attention = True
                self.state.add_note(
                    "Content editor had failed edit attempts and made no "
                    f"changes: {params.summary}"
                )
                return self._finish(
                    "request_human_review",
                    params.summary,
                    error=(
                        "commit rejected after failed edit attempts with no "
                        "successful mutation"
                    ),
                )
        elif params.resolution == "request_human_review":
            self.state.approval = Approval.PROPOSED
            self.state.needs_attention = True
            self.state.add_note(params.summary)
        elif params.resolution == "abort":
            self.state.current.description = self._original_text
            self.state.approval = Approval.REJECTED
            self.state.add_note(params.summary)
        else:
            return self._error(
                "resolution must be commit, abort, or request_human_review"
            )
        return self._finish(params.resolution, params.summary)

    @llm_tool
    def complain(self, params: ComplainParams) -> dict[str, Any]:
        """Suggest improvements to this editing API."""
        note = f"Content editor complaint: {params.complaint}"
        if params.suggestion:
            note += f" Suggestion: {params.suggestion}"
        self.state.needs_attention = True
        self.state.add_note(note)
        return {"status": "complaint_recorded"}

    def should_stop(self, message: Any, tool_results: Any, step: int) -> bool:
        return self._finished

    def _current_text(self) -> str:
        return self.state.current.description or ""

    def _content(self, text: str | None, source: SourceRef | None) -> str:
        if source == SourceRef("", 0, 0):
            source = None
        if (text is None) == (source is None):
            raise ValueError("provide exactly one of text or source")
        if source is None:
            assert text is not None
            return text
        if source.file not in self._readonly_files:
            raise ValueError(
                f"unknown readonly source {source.file!r}; "
                f"available: {', '.join(self._readonly_files) or '(none)'}"
            )
        data = self._readonly_files[source.file]
        start, end = _range(data, source.start_line, source.end_line)
        return data[start:end]

    def _apply_text(self, text: str) -> None:
        self._undo_stack.append(self._current_text())
        self.state.current.description = text
        self._successful_mutations += 1

    def _finish(
        self, resolution: str, summary: str, *, error: str | None = None
    ) -> dict[str, Any]:
        self._finished = True
        result: dict[str, Any] = {
            "status": "finished",
            "resolution": resolution,
            "summary": summary,
        }
        if error:
            result["error"] = error
        return result

    def _success(self, status: str) -> dict[str, Any]:
        return {
            "status": status,
            "message": "Inspect numbered current; call finish when done.",
            "current_text": self._current_text(),
            "current_file": _display(
                "current", self._current_text(), editable=True
            ),
        }

    def _error(self, error: object) -> dict[str, Any]:
        self._failed_mutations += 1
        return {
            "status": "error",
            "error": str(error),
            "current_text": self._current_text(),
            "current_file": _display(
                "current", self._current_text(), editable=True
            ),
        }
