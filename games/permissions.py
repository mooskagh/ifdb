from django.contrib.auth.models import AnonymousUser

from core.models import User
from games.models import Game, Personality


def can_view_game(user: User | AnonymousUser, game: Game) -> bool:
    if game.state == Game.State.PUBLISHED:
        return True
    return bool(user.is_authenticated and user.is_superuser)


def can_edit_game(
    user: User | AnonymousUser, game: Game | None = None
) -> bool:
    if not user.is_authenticated:
        return False
    return bool(
        user.is_staff
        or user.is_superuser
        or user.groups.filter(name="moder").exists()
    )


def can_delete_game(user: User | AnonymousUser, game: Game) -> bool:
    return bool(user.is_authenticated and user.is_superuser)


def can_comment_game(user: User | AnonymousUser, game: Game) -> bool:
    return bool(user.is_authenticated and user.is_active)


def can_vote_game(user: User | AnonymousUser, game: Game) -> bool:
    return bool(user.is_authenticated and user.is_active)


def can_add_game(user: User | AnonymousUser) -> bool:
    return bool(user.is_authenticated and user.is_active)


def can_view_author(user: User | AnonymousUser, author: Personality) -> bool:
    return True


def can_edit_author(
    user: User | AnonymousUser, author: Personality | None = None
) -> bool:
    if not user.is_authenticated:
        return False
    return bool(
        user.is_staff
        or user.is_superuser
        or user.groups.filter(name="moder").exists()
    )


def can_delete_author(user: User | AnonymousUser, author: Personality) -> bool:
    return bool(user.is_authenticated and user.is_superuser)
