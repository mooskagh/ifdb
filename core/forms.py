from .models import User

import registration.forms


class RegistrationForm(registration.forms.RegistrationForm):
    class Meta:
        model = User
        fields = ['email', 'username']