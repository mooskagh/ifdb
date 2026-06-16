from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class Segment:
    text: str
    kind: str


@dataclass(frozen=True)
class DiffRow:
    tag: str
    left_no: int | None
    right_no: int | None
    left: list[Segment]
    right: list[Segment]


def _char_segments(
    before: str, after: str
) -> tuple[list[Segment], list[Segment]]:
    left = []
    right = []
    matcher = SequenceMatcher(None, before, after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            left.append(Segment(before[i1:i2], "equal"))
            right.append(Segment(after[j1:j2], "equal"))
        else:
            if i1 != i2:
                left.append(Segment(before[i1:i2], "del"))
            if j1 != j2:
                right.append(Segment(after[j1:j2], "ins"))
    return left, right


def build_diff(before: str, after: str) -> list[DiffRow]:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    rows = []
    matcher = SequenceMatcher(None, before_lines, after_lines, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for left_idx, right_idx in zip(
                range(i1, i2), range(j1, j2), strict=True
            ):
                rows.append(
                    DiffRow(
                        "equal",
                        left_idx + 1,
                        right_idx + 1,
                        [Segment(before_lines[left_idx], "equal")],
                        [Segment(after_lines[right_idx], "equal")],
                    )
                )
        elif tag == "delete":
            rows.extend(
                DiffRow(
                    "delete",
                    idx + 1,
                    None,
                    [Segment(before_lines[idx], "del")],
                    [],
                )
                for idx in range(i1, i2)
            )
        elif tag == "insert":
            rows.extend(
                DiffRow(
                    "insert",
                    None,
                    idx + 1,
                    [],
                    [Segment(after_lines[idx], "ins")],
                )
                for idx in range(j1, j2)
            )
        else:
            paired = min(i2 - i1, j2 - j1)
            for offset in range(paired):
                left_idx = i1 + offset
                right_idx = j1 + offset
                left, right = _char_segments(
                    before_lines[left_idx], after_lines[right_idx]
                )
                rows.append(
                    DiffRow(
                        "replace", left_idx + 1, right_idx + 1, left, right
                    )
                )
            rows.extend(
                DiffRow(
                    "delete",
                    idx + 1,
                    None,
                    [Segment(before_lines[idx], "del")],
                    [],
                )
                for idx in range(i1 + paired, i2)
            )
            rows.extend(
                DiffRow(
                    "insert",
                    None,
                    idx + 1,
                    [],
                    [Segment(after_lines[idx], "ins")],
                )
                for idx in range(j1 + paired, j2)
            )
    return rows
