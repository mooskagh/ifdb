from typing import Any

import django_registration.forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _
from django_recaptcha.fields import ReCaptchaField

from .models import User


class RegistrationForm(django_registration.forms.RegistrationForm):
    class Meta:
        model = User
        fields = ["email", "username"]

    captcha = ReCaptchaField(label="А вы не робот?")


class LoginForm(AuthenticationForm):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["username"].label = _("Логин или email")
