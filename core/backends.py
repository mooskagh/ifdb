from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.base_user import AbstractBaseUser
from django.db.models import Q
from django.http import HttpRequest


class EmailOrUsernameModelBackend(ModelBackend):
    """Authentication backend allowing login with either email or username."""

    def authenticate(
        self,
        request: HttpRequest | None = None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> AbstractBaseUser | None:
        user_model = get_user_model()
        if username is None:
            username = kwargs.get(
                getattr(user_model, "USERNAME_FIELD", "email")
            )
        if not username or not password:
            return None

        user_list = list(
            user_model.objects.filter(
                Q(email__iexact=username) | Q(username__iexact=username)
            )
        )

        for user in user_list:
            if user.check_password(password) and self.user_can_authenticate(
                user
            ):
                return user

        if not user_list:
            user_model().set_password(password)

        return None
