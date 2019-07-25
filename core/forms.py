from .models import User

import registration.forms
from captcha.fields import ReCaptchaField


class RegistrationForm(registration.forms.RegistrationForm):
    class Meta:
        model = User
        fields = ['email', 'username']

    captcha = ReCaptchaField(label='А вы не робот?')