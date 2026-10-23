from django.http import HttpRequest, HttpResponse
from django.test import SimpleTestCase, override_settings

from core.cors import (
    cors_playable,
    is_allowed_playable_origin,
    playable_cors,
    set_cors_headers,
)


class CorsTests(SimpleTestCase):
    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz", DEBUG=False)
    def test_is_allowed_playable_origin(self) -> None:
        self.assertTrue(
            is_allowed_playable_origin("https://danetka.play.crem.xyz")
        )
        self.assertTrue(
            is_allowed_playable_origin("http://sub.danetka.play.crem.xyz")
        )
        self.assertTrue(is_allowed_playable_origin("https://play.crem.xyz"))
        self.assertTrue(
            is_allowed_playable_origin("https://danetka.play.crem.xyz:8443")
        )

        self.assertFalse(
            is_allowed_playable_origin("https://evilplay.crem.xyz")
        )
        self.assertFalse(is_allowed_playable_origin("https://evil.com"))
        self.assertFalse(is_allowed_playable_origin("http://localhost:3000"))
        self.assertFalse(is_allowed_playable_origin(""))
        self.assertFalse(is_allowed_playable_origin(None))

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz", DEBUG=True)
    def test_is_allowed_playable_origin_debug(self) -> None:
        self.assertTrue(is_allowed_playable_origin("http://localhost:8000"))
        self.assertTrue(is_allowed_playable_origin("http://127.0.0.1:3000"))
        self.assertTrue(is_allowed_playable_origin("http://0.0.0.0:8080"))
        self.assertFalse(is_allowed_playable_origin("https://evil.com"))

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_set_cors_headers_allowed_origin(self) -> None:
        request = HttpRequest()
        request.META["HTTP_ORIGIN"] = "https://danetka.play.crem.xyz"
        response = HttpResponse()

        res = set_cors_headers(request, response, methods="GET")
        self.assertEqual(
            res["Access-Control-Allow-Origin"], "https://danetka.play.crem.xyz"
        )
        self.assertEqual(res["Access-Control-Allow-Credentials"], "true")
        self.assertEqual(res["Access-Control-Allow-Methods"], "GET")
        self.assertEqual(res["Access-Control-Allow-Headers"], "Content-Type")

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_set_cors_headers_disallowed_origin(self) -> None:
        request = HttpRequest()
        request.META["HTTP_ORIGIN"] = "https://evil.com"
        response = HttpResponse()

        res = set_cors_headers(request, response)
        self.assertNotIn("Access-Control-Allow-Origin", res)
        self.assertNotIn("Access-Control-Allow-Credentials", res)

    def test_set_cors_headers_no_origin(self) -> None:
        request = HttpRequest()
        response = HttpResponse()

        res = set_cors_headers(request, response)
        self.assertNotIn("Access-Control-Allow-Origin", res)

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_cors_playable_decorator(self) -> None:
        @cors_playable(methods="GET")
        def view(req: HttpRequest) -> HttpResponse:
            return HttpResponse("ok", status=200)

        request = HttpRequest()
        request.META["HTTP_ORIGIN"] = "https://danetka.play.crem.xyz"
        res = view(request)
        self.assertEqual(
            res["Access-Control-Allow-Origin"], "https://danetka.play.crem.xyz"
        )
        self.assertEqual(res["Access-Control-Allow-Methods"], "GET")

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_cors_playable_decorator_default_methods(self) -> None:
        @playable_cors
        def view(req: HttpRequest) -> HttpResponse:
            return HttpResponse("ok", status=200)

        request = HttpRequest()
        request.META["HTTP_ORIGIN"] = "https://danetka.play.crem.xyz"
        res = view(request)
        self.assertEqual(
            res["Access-Control-Allow-Origin"], "https://danetka.play.crem.xyz"
        )
        self.assertEqual(res["Access-Control-Allow-Methods"], "GET")
