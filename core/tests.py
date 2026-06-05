from django.conf import settings
from django.test import SimpleTestCase


class CeleryTestSettingsTest(SimpleTestCase):
    def test_tests_use_in_memory_celery_broker(self):
        self.assertEqual(settings.CELERY_BROKER_URL, "memory://")
        self.assertEqual(settings.CELERY_RESULT_BACKEND, "cache+memory://")
        self.assertFalse(
            getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False),
            "Tests should not execute queued tasks implicitly.",
        )
