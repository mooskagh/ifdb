from django.test import TestCase

from curation.edit import Approval, GameEditState
from curation.gameinfo import GameInfo, Person
from curation.passes.dedup_personality_aliases import (
    DedupPersonalityAliasesPass,
)
from games.models import Personality, PersonalityAlias


class DedupPersonalityAliasesPassTest(TestCase):
    def _state(self, current: GameInfo, served: GameInfo | None = None):
        return GameEditState(
            history=None,
            current=current,
            approval=Approval.APPLIED,
            served=served or GameInfo(),
            last_applied=GameInfo(),
            sources=[],
        )

    def _apply(self, current: GameInfo, served: GameInfo | None = None):
        state = self._state(current, served)
        DedupPersonalityAliasesPass().apply(state, {})
        return state.current

    def _aliases(self):
        personality = Personality.objects.create(name="Jane")
        return (
            PersonalityAlias.objects.create(
                name="Jane", personality=personality
            ),
            PersonalityAlias.objects.create(
                name="J. Doe", personality=personality
            ),
        )

    def test_collapses_aliases_to_same_personality_in_same_role(self):
        first, second = self._aliases()

        info = self._apply(
            GameInfo(
                personalities={
                    "author": [Person(first.id, ""), Person(second.id, "")]
                }
            )
        )

        self.assertEqual(info.personalities["author"], [Person(first.id, "")])

    def test_served_alias_wins_for_same_role_and_personality(self):
        served_alias, source_alias = self._aliases()

        info = self._apply(
            GameInfo(personalities={"author": [Person(source_alias.id, "")]}),
            GameInfo(personalities={"author": [Person(served_alias.id, "")]}),
        )

        self.assertEqual(
            info.personalities["author"], [Person(served_alias.id, "")]
        )

    def test_same_personality_in_different_roles_is_preserved(self):
        first, second = self._aliases()

        info = self._apply(
            GameInfo(
                personalities={
                    "author": [Person(first.id, "")],
                    "artist": [Person(second.id, "")],
                }
            )
        )

        self.assertEqual(info.personalities["author"], [Person(first.id, "")])
        self.assertEqual(info.personalities["artist"], [Person(second.id, "")])

    def test_preserves_unresolved_and_unattached_aliases(self):
        alias = PersonalityAlias.objects.create(name="Loose")
        current = GameInfo(
            personalities={
                "author": [
                    Person(None, "Unresolved"),
                    Person(None, "Unresolved"),
                    Person(alias.id, ""),
                    Person(alias.id, ""),
                ]
            }
        )

        info = self._apply(current)

        self.assertEqual(
            info.personalities["author"],
            [
                Person(None, "Unresolved"),
                Person(None, "Unresolved"),
                Person(alias.id, ""),
                Person(alias.id, ""),
            ],
        )
