from django.test import Client, TestCase
from django.urls import reverse


class APIDocsTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()

    def test_openapi_json(self) -> None:
        response = self.client.get(reverse("api_openapi"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["openapi"], "3.0.3")
        self.assertEqual(data["info"]["title"], "IFDB REST API")
        self.assertIn("/api/v1/games/", data["paths"])
        self.assertIn("/api/v1/files/", data["paths"])

    def test_api_docs_html(self) -> None:
        response = self.client.get(reverse("api_docs"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["content-type"])
        self.assertIn("redoc", response.content.decode("utf-8"))
