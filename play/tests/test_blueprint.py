from django.test import SimpleTestCase

from play.blueprint import (
    TELEMETRY_SCRIPT,
    TELEMETRY_SCRIPT_BYTES,
    insert_telemetry,
)


class InsertTelemetryTests(SimpleTestCase):
    def test_inserts_before_closing_body_tag(self) -> None:
        cases = (
            (
                "<html><body><h1>Hi</h1></body></html>",
                f"<html><body><h1>Hi</h1>{TELEMETRY_SCRIPT}</body></html>",
            ),
            (
                "<html><body><h1>Hi</h1></BODY></html>",
                f"<html><body><h1>Hi</h1>{TELEMETRY_SCRIPT}</BODY></html>",
            ),
            (
                "<html><body><h1>Hi</h1></body ></html>",
                f"<html><body><h1>Hi</h1>{TELEMETRY_SCRIPT}</body ></html>",
            ),
        )
        for html_input, expected in cases:
            with self.subTest(html_input=html_input):
                self.assertEqual(insert_telemetry(html_input), expected)

    def test_inserts_before_final_body_tag_when_multiple(self) -> None:
        html_input = (
            "<html><body><div>fake </body> inside</div>"
            "<div>real</div></body></html>"
        )
        expected = (
            "<html><body><div>fake </body> inside</div><div>real</div>"
            f"{TELEMETRY_SCRIPT}</body></html>"
        )
        self.assertEqual(insert_telemetry(html_input), expected)

    def test_inserts_before_closing_html_tag_when_no_body(self) -> None:
        prefix = "<html><head><title>Test</title></head>"
        cases = (
            (
                f"{prefix}</html>",
                f"{prefix}{TELEMETRY_SCRIPT}</html>",
            ),
            (
                f"{prefix}</HTML>",
                f"{prefix}{TELEMETRY_SCRIPT}</HTML>",
            ),
            (
                f"{prefix}</html >",
                f"{prefix}{TELEMETRY_SCRIPT}</html >",
            ),
        )
        for html_input, expected in cases:
            with self.subTest(html_input=html_input):
                self.assertEqual(insert_telemetry(html_input), expected)

    def test_inserts_before_final_html_tag_when_multiple_and_no_body(
        self,
    ) -> None:
        html_input = "<html>Some </html> text </html>"
        expected = f"<html>Some </html> text {TELEMETRY_SCRIPT}</html>"
        self.assertEqual(insert_telemetry(html_input), expected)

    def test_appends_to_end_when_neither_body_nor_html_exists(self) -> None:
        html_input = "<h1>Hello world</h1>"
        expected = f"<h1>Hello world</h1>{TELEMETRY_SCRIPT}"
        self.assertEqual(insert_telemetry(html_input), expected)

    def test_idempotent_when_telemetry_already_present(self) -> None:
        html_input = f"<html><body>{TELEMETRY_SCRIPT}</body></html>"
        self.assertEqual(insert_telemetry(html_input), html_input)

    def test_bytes_support(self) -> None:
        # Before </body>
        html_bytes = b"<html><body><h1>Hi</h1></body></html>"
        expected = (
            b"<html><body><h1>Hi</h1>"
            + TELEMETRY_SCRIPT_BYTES
            + b"</body></html>"
        )
        self.assertEqual(insert_telemetry(html_bytes), expected)

        # Before </html>
        html_bytes = b"<html><head></head></html>"
        expected = b"<html><head></head>" + TELEMETRY_SCRIPT_BYTES + b"</html>"
        self.assertEqual(insert_telemetry(html_bytes), expected)

        # Append to end
        html_bytes = b"<h1>Fragment</h1>"
        expected = b"<h1>Fragment</h1>" + TELEMETRY_SCRIPT_BYTES
        self.assertEqual(insert_telemetry(html_bytes), expected)

        # Idempotent
        already = b"<html><body>" + TELEMETRY_SCRIPT_BYTES + b"</body></html>"
        self.assertEqual(insert_telemetry(already), already)
