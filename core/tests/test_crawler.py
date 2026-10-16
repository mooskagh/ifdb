import email.message
from unittest import TestCase

from core.crawler import _ResponseInfoToMetadata, decode_mojibake_filename


class CrawlerFilenameDecodeTests(TestCase):
    def test_decode_mojibake_utf8_as_latin1(self) -> None:
        self.assertEqual(
            decode_mojibake_filename("ÐºÐ°Ñ\x80Ð°Ð½Ñ\x82Ð¸Ð½.qsz"),
            "карантин.qsz",
        )

    def test_decode_mojibake_utf8_as_cp1252(self) -> None:
        self.assertEqual(
            decode_mojibake_filename("ÐºÐ°Ñ€Ð°Ð½Ñ‚Ð¸Ð½.qsz"),
            "карантин.qsz",
        )

    def test_decode_mojibake_cp1251_as_latin1(self) -> None:
        self.assertEqual(
            decode_mojibake_filename("êàðàíòèí.qsz"),
            "карантин.qsz",
        )

    def test_decode_mojibake_percent_encoded_cp1251(self) -> None:
        self.assertEqual(
            decode_mojibake_filename(
                "%C3%AA%C3%A0%C3%B0%C3%A0%C3%AD%C3%B2%C3%A8%C3%AD.qsz"
            ),
            "карантин.qsz",
        )
        self.assertEqual(
            decode_mojibake_filename("%EA%E0%F0%E0%ED%F2%E8%ED.qsz"),
            "карантин.qsz",
        )

    def test_decode_mojibake_percent_encoded_utf8(self) -> None:
        self.assertEqual(
            decode_mojibake_filename(
                "%D0%BA%D0%B0%D1%80%D0%B0%D0%BD%D1%82%D0%B8%D0%BD.qsz"
            ),
            "карантин.qsz",
        )

    def test_decode_mojibake_rfc2047(self) -> None:
        self.assertEqual(
            decode_mojibake_filename(
                "=?UTF-8?B?0LrQsNGA0LDQvdGC0LjQvS5xc3o=?="
            ),
            "карантин.qsz",
        )

    def test_preserves_legitimate_latin1_and_ascii(self) -> None:
        self.assertEqual(
            decode_mojibake_filename("Möjlighet-1.0-pc.zip"),
            "Möjlighet-1.0-pc.zip",
        )
        self.assertEqual(
            decode_mojibake_filename("café.zip"),
            "café.zip",
        )
        self.assertEqual(
            decode_mojibake_filename("archive_0.3.rar"),
            "archive_0.3.rar",
        )

    def test_preserves_already_clean_cyrillic(self) -> None:
        self.assertEqual(
            decode_mojibake_filename("карантин.qsz"),
            "карантин.qsz",
        )

    def test_handles_none_and_empty(self) -> None:
        self.assertIsNone(decode_mojibake_filename(None))
        self.assertEqual(decode_mojibake_filename(""), "")
        self.assertEqual(decode_mojibake_filename("   "), "")

    def test_strips_extraneous_quotes(self) -> None:
        self.assertEqual(
            decode_mojibake_filename('"карантин.qsz"'),
            "карантин.qsz",
        )

    def test_response_info_to_metadata_extracts_and_decodes_filename(
        self,
    ) -> None:
        msg = email.message.Message()
        msg["Content-Type"] = "application/octet-stream"
        msg["Content-Disposition"] = (
            'attachment; filename="ÐºÐ°Ñ\x80Ð°Ð½Ñ\x82Ð¸Ð½.qsz"; size = "33239"'
        )
        meta = _ResponseInfoToMetadata(
            "http://example.com/file.php?i=1",
            msg,
            final_url="https://example.com/file.php?i=1",
        )
        self.assertEqual(meta["filename"], "карантин.qsz")
        self.assertEqual(meta["final_url"], "https://example.com/file.php?i=1")
