from django.contrib.auth.models import AnonymousUser

from contest.models import Competition, CompetitionDocument
from core.models import User


def can_admin_competition(
    user: User | AnonymousUser, comp: Competition
) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool(comp.owner_id is not None and comp.owner_id == user.id)


def can_view_competition(
    user: User | AnonymousUser, comp: Competition
) -> bool:
    return True


def can_view_competition_document(
    user: User | AnonymousUser, doc: CompetitionDocument
) -> bool:
    return True
