from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from core.backends import EmailOrUsernameModelBackend
from core.forms import LoginForm


class EmailOrUsernameModelBackendTest(SimpleTestCase):
    databases: set[str] = set()

    def setUp(self) -> None:
        self.backend = EmailOrUsernameModelBackend()

    @patch("core.backends.get_user_model")
    def test_authenticate_by_email_success(
        self, mock_get_user_model: MagicMock
    ) -> None:
        mock_user_model = MagicMock()
        mock_get_user_model.return_value = mock_user_model
        mock_user = MagicMock()
        mock_user.check_password.return_value = True
        mock_user.is_active = True
        mock_user_model.objects.filter.return_value = [mock_user]

        result = self.backend.authenticate(
            None, username="user@example.com", password="secretpassword"
        )
        self.assertEqual(result, mock_user)
        mock_user.check_password.assert_called_once_with("secretpassword")

    @patch("core.backends.get_user_model")
    def test_authenticate_by_username_success(
        self, mock_get_user_model: MagicMock
    ) -> None:
        mock_user_model = MagicMock()
        mock_get_user_model.return_value = mock_user_model
        mock_user = MagicMock()
        mock_user.check_password.return_value = True
        mock_user.is_active = True
        mock_user_model.objects.filter.return_value = [mock_user]

        result = self.backend.authenticate(
            None, username="coolgamer", password="secretpassword"
        )
        self.assertEqual(result, mock_user)
        mock_user.check_password.assert_called_once_with("secretpassword")

    @patch("core.backends.get_user_model")
    def test_authenticate_wrong_password(
        self, mock_get_user_model: MagicMock
    ) -> None:
        mock_user_model = MagicMock()
        mock_get_user_model.return_value = mock_user_model
        mock_user = MagicMock()
        mock_user.check_password.return_value = False
        mock_user.is_active = True
        mock_user_model.objects.filter.return_value = [mock_user]

        result = self.backend.authenticate(
            None, username="coolgamer", password="wrongpassword"
        )
        self.assertIsNone(result)

    @patch("core.backends.get_user_model")
    def test_authenticate_inactive_user(
        self, mock_get_user_model: MagicMock
    ) -> None:
        mock_user_model = MagicMock()
        mock_get_user_model.return_value = mock_user_model
        mock_user = MagicMock()
        mock_user.check_password.return_value = True
        mock_user.is_active = False
        mock_user_model.objects.filter.return_value = [mock_user]

        result = self.backend.authenticate(
            None, username="inactive_user", password="secretpassword"
        )
        self.assertIsNone(result)

    @patch("core.backends.get_user_model")
    def test_authenticate_user_not_found(
        self, mock_get_user_model: MagicMock
    ) -> None:
        mock_user_model = MagicMock()
        mock_dummy_user = MagicMock()
        mock_user_model.return_value = mock_dummy_user
        mock_get_user_model.return_value = mock_user_model
        mock_user_model.objects.filter.return_value = []

        result = self.backend.authenticate(
            None, username="nonexistent", password="somepassword"
        )
        self.assertIsNone(result)
        mock_dummy_user.set_password.assert_called_once_with("somepassword")

    def test_authenticate_empty_credentials(self) -> None:
        self.assertIsNone(
            self.backend.authenticate(None, username="", password="pwd")
        )
        self.assertIsNone(
            self.backend.authenticate(None, username="user", password="")
        )
        self.assertIsNone(
            self.backend.authenticate(None, username=None, password="pwd")
        )


class LoginFormTest(SimpleTestCase):
    databases: set[str] = set()

    def test_login_form_username_label(self) -> None:
        form = LoginForm()
        self.assertEqual(str(form.fields["username"].label), "Логин или email")
