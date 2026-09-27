import json
from dataclasses import dataclass
from difflib import SequenceMatcher

_JSON_DECODER = json.JSONDecoder()


def _extract_database_id(line: str) -> tuple[str, int] | None:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None
    content = stripped[2:].strip()
    try:
        obj, _ = _JSON_DECODER.raw_decode(content)
    except Exception:
        return None
    if isinstance(obj, list):
        if len(obj) == 3 and isinstance(obj[2], int):
            return ("url", obj[2])
        if len(obj) == 2 and isinstance(obj[1], int):
            return ("tag", obj[1])
    elif isinstance(obj, int):
        if line.startswith("    - "):
            return ("personality", obj)
        return ("attribution", obj)
    return None


def _find_frontmatter_lines(lines: list[str]) -> set[int]:
    if not lines or lines[0] != "---":
        return set()
    for idx in range(1, len(lines)):
        if lines[idx] == "---":
            return set(range(1, idx))
    return set(range(1, len(lines)))


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
    left_text: str = ""
    right_text: str = ""

    @property
    def line_text(self) -> str:
        return self.right_text or self.left_text

    @property
    def default_checked(self) -> bool:
        return self.tag != "delete"


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


def build_diff(
    before: str, after: str, *, pair_lines: bool = True
) -> list[DiffRow]:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    before_fm = _find_frontmatter_lines(before_lines)
    after_fm = _find_frontmatter_lines(after_lines)
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
                        left_text=before_lines[left_idx],
                        right_text=after_lines[right_idx],
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
                    left_text=before_lines[idx],
                    right_text="",
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
                    left_text="",
                    right_text=after_lines[idx],
                )
                for idx in range(j1, j2)
            )
        else:
            if pair_lines:
                left_indices = list(range(i1, i2))
                right_indices = list(range(j1, j2))

                matched_id_pairs: list[tuple[int, int]] = []
                used_right: set[int] = set()
                last_ri = -1
                for li in left_indices:
                    lid = (
                        _extract_database_id(before_lines[li])
                        if li in before_fm
                        else None
                    )
                    if lid is not None:
                        for ri in right_indices:
                            if ri > last_ri and ri not in used_right:
                                rid = (
                                    _extract_database_id(after_lines[ri])
                                    if ri in after_fm
                                    else None
                                )
                                if rid == lid:
                                    matched_id_pairs.append((li, ri))
                                    used_right.add(ri)
                                    last_ri = ri
                                    break

                intervals: list[tuple[int, int, int, int]] = []
                prev_l, prev_r = i1, j1
                for pl, pr in matched_id_pairs:
                    intervals.append((prev_l, pl, prev_r, pr))
                    prev_l, prev_r = pl + 1, pr + 1
                intervals.append((prev_l, i2, prev_r, j2))

                all_pairs = list(matched_id_pairs)
                for l_start, l_end, r_start, r_end in intervals:
                    b_left = [
                        li
                        for li in range(l_start, l_end)
                        if (
                            _extract_database_id(before_lines[li])
                            if li in before_fm
                            else None
                        )
                        is None
                    ]
                    b_right = [
                        ri
                        for ri in range(r_start, r_end)
                        if (
                            _extract_database_id(after_lines[ri])
                            if ri in after_fm
                            else None
                        )
                        is None
                    ]
                    for k in range(min(len(b_left), len(b_right))):
                        all_pairs.append((b_left[k], b_right[k]))

                all_pairs.sort()

                cur_l = i1
                cur_r = j1
                for pair_l, pair_r in all_pairs:
                    while cur_l < pair_l:
                        rows.append(
                            DiffRow(
                                "delete",
                                cur_l + 1,
                                None,
                                [Segment(before_lines[cur_l], "del")],
                                [],
                                left_text=before_lines[cur_l],
                                right_text="",
                            )
                        )
                        cur_l += 1
                    while cur_r < pair_r:
                        rows.append(
                            DiffRow(
                                "insert",
                                None,
                                cur_r + 1,
                                [],
                                [Segment(after_lines[cur_r], "ins")],
                                left_text="",
                                right_text=after_lines[cur_r],
                            )
                        )
                        cur_r += 1
                    left, right = _char_segments(
                        before_lines[pair_l], after_lines[pair_r]
                    )
                    rows.append(
                        DiffRow(
                            "replace",
                            pair_l + 1,
                            pair_r + 1,
                            left,
                            right,
                            left_text=before_lines[pair_l],
                            right_text=after_lines[pair_r],
                        )
                    )
                    cur_l = pair_l + 1
                    cur_r = pair_r + 1

                while cur_l < i2:
                    rows.append(
                        DiffRow(
                            "delete",
                            cur_l + 1,
                            None,
                            [Segment(before_lines[cur_l], "del")],
                            [],
                            left_text=before_lines[cur_l],
                            right_text="",
                        )
                    )
                    cur_l += 1
                while cur_r < j2:
                    rows.append(
                        DiffRow(
                            "insert",
                            None,
                            cur_r + 1,
                            [],
                            [Segment(after_lines[cur_r], "ins")],
                            left_text="",
                            right_text=after_lines[cur_r],
                        )
                    )
                    cur_r += 1
            else:
                rows.extend(
                    DiffRow(
                        "delete",
                        idx + 1,
                        None,
                        [Segment(before_lines[idx], "del")],
                        [],
                        left_text=before_lines[idx],
                        right_text="",
                    )
                    for idx in range(i1, i2)
                )
                rows.extend(
                    DiffRow(
                        "insert",
                        None,
                        idx + 1,
                        [],
                        [Segment(after_lines[idx], "ins")],
                        left_text="",
                        right_text=after_lines[idx],
                    )
                    for idx in range(j1, j2)
                )
    return rows
