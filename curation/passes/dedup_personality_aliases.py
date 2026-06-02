"""Collapse duplicate aliases to the same personality within a role."""

from curation.edit import GameEditPass, GameEditState, register_pass
from curation.gameinfo import Person
from games.models import PersonalityAlias


@register_pass
class DedupPersonalityAliasesPass(GameEditPass):
    name = "dedup_personality_aliases"

    def apply(self, state: GameEditState, params: dict) -> None:
        alias_to_personality = _alias_to_personality(state)
        served = _served_aliases(state, alias_to_personality)

        for role, people in list(state.current.personalities.items()):
            seen: set[int] = set()
            result = []
            for person in people:
                personality_id = _personality_id(person, alias_to_personality)
                if personality_id is None:
                    result.append(person)
                    continue
                if personality_id in seen:
                    continue
                seen.add(personality_id)
                result.append(served.get((role, personality_id), person))
            state.current.personalities[role] = result


def _alias_to_personality(state: GameEditState) -> dict[int, int | None]:
    alias_ids = {
        person.alias_id
        for info in (state.current, state.served)
        for people in info.personalities.values()
        for person in people
        if person.alias_id is not None
    }
    return dict(
        PersonalityAlias.objects.filter(id__in=alias_ids).values_list(
            "id", "personality_id"
        )
    )


def _served_aliases(
    state: GameEditState, alias_to_personality: dict[int, int | None]
) -> dict[tuple[str, int], Person]:
    result = {}
    for role, people in state.served.personalities.items():
        for person in people:
            personality_id = _personality_id(person, alias_to_personality)
            if personality_id is not None:
                result.setdefault((role, personality_id), person)
    return result


def _personality_id(
    person: Person, alias_to_personality: dict[int, int | None]
) -> int | None:
    if person.alias_id is None:
        return None
    return alias_to_personality.get(person.alias_id)
