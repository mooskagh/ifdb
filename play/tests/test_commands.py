from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils.timezone import now

from games.models import Game
from play.management.commands.regenerate_playables import (
    is_version_newer,
    version_sort_key,
)
from play.models import Playable


class VersionComparisonTests(TestCase):
    def test_version_sort_key(self) -> None:
        self.assertEqual(version_sort_key(""), ())
        self.assertEqual(version_sort_key("1.2.3"), ((0, 1), (0, 2), (0, 3)))
        self.assertEqual(
            version_sort_key("2026-08-23"), ((0, 2026), (0, 8), (0, 23))
        )
        self.assertEqual(version_sort_key("1.0b1"), ((0, 1), (1, "0b1")))

    def test_is_version_newer(self) -> None:
        self.assertTrue(is_version_newer("1.3.1", "1.2.0"))
        self.assertFalse(is_version_newer("1.3.1", "1.3.1"))
        self.assertFalse(is_version_newer("1.2.0", "1.3.1"))
        self.assertTrue(is_version_newer("2026-08-23", "2025-01-01"))
        self.assertFalse(is_version_newer("2025-01-01", "2026-08-23"))
        self.assertTrue(is_version_newer("1.0", ""))
        self.assertFalse(is_version_newer("", "1.0"))
        self.assertFalse(is_version_newer("1", "1"))
        self.assertTrue(is_version_newer("2", "1"))

        # Available versions list ordering
        avail = ["1.0", "1.2", "2.0"]
        self.assertTrue(is_version_newer("2.0", "1.0", avail))
        self.assertFalse(is_version_newer("1.0", "2.0", avail))
        self.assertFalse(is_version_newer("1.0", "1.0", avail))


class RegeneratePlayablesCommandTests(TestCase):
    game: Game

    @classmethod
    def setUpTestData(cls) -> None:
        cls.game = Game.objects.create(
            title="Test Adventure",
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )

    def test_dry_run_all(self) -> None:
        p1 = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.5.2",
            state=Playable.State.READY,
        )
        p2 = Playable.objects.create(
            game=self.game,
            template="qspider",
            template_version="1.3.1",
            state=Playable.State.READY,
        )

        out = StringIO()
        call_command("regenerate_playables", dry_run=True, stdout=out)
        output = out.getvalue()

        self.assertIn("[DRY RUN] Found 2 playable(s) to regenerate:", output)
        self.assertIn(f"#{p1.pk}: Test Adventure [instead_em 3.5.2]", output)
        self.assertIn(f"#{p2.pk}: Test Adventure [qspider 1.3.1]", output)
        self.assertIn(
            "Dry run complete: 2 playable(s) would be regenerated.", output
        )

        # Ensure nothing was changed
        p1.refresh_from_db()
        self.assertEqual(p1.state, Playable.State.READY)

    def test_filter_by_player_slug_and_display_name(self) -> None:
        p_instead = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.5.2",
            state=Playable.State.READY,
        )
        p_qsp = Playable.objects.create(
            game=self.game,
            template="qspider",
            template_version="1.3.1",
            state=Playable.State.READY,
        )

        # By slug
        out = StringIO()
        call_command(
            "regenerate_playables",
            player_type="qspider",
            dry_run=True,
            stdout=out,
        )
        output = out.getvalue()
        self.assertIn(f"#{p_qsp.pk}: Test Adventure [qspider 1.3.1]", output)
        self.assertNotIn(f"#{p_instead.pk}", output)

        # By display name
        out = StringIO()
        call_command(
            "regenerate_playables",
            player_type="INSTEAD Emscripten",
            dry_run=True,
            stdout=out,
        )
        output = out.getvalue()
        self.assertIn(
            f"#{p_instead.pk}: Test Adventure [instead_em 3.5.2]", output
        )
        self.assertNotIn(f"#{p_qsp.pk}", output)

    def test_filter_by_unknown_player_raises(self) -> None:
        with self.assertRaises(CommandError) as ctx:
            call_command("regenerate_playables", player_type="unknown_player")
        self.assertIn(
            "Unknown player type 'unknown_player'", str(ctx.exception)
        )
        self.assertIn("instead_em", str(ctx.exception))

    def test_filter_by_version(self) -> None:
        p1 = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.4.0",
            state=Playable.State.READY,
        )
        p2 = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.5.2",
            state=Playable.State.READY,
        )

        out = StringIO()
        call_command(
            "regenerate_playables", version="3.4.0", dry_run=True, stdout=out
        )
        output = out.getvalue()
        self.assertIn(f"#{p1.pk}: Test Adventure", output)
        self.assertNotIn(f"#{p2.pk}", output)

    def test_update_outdated_mode(self) -> None:
        # Latest instead_em in assets is 3.5.2
        outdated = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.4.0",
            state=Playable.State.READY,
        )
        up_to_date = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.5.2",
            state=Playable.State.READY,
        )

        out = StringIO()
        call_command(
            "regenerate_playables",
            update_outdated=True,
            dry_run=True,
            stdout=out,
        )
        output = out.getvalue()
        self.assertIn(
            f"#{outdated.pk}: Test Adventure [instead_em 3.4.0 -> 3.5.2]",
            output,
        )
        self.assertNotIn(f"#{up_to_date.pk}", output)
        self.assertIn(
            "Dry run complete: 1 playable(s) would be regenerated.", output
        )

    def test_building_playables_skipped_by_default(self) -> None:
        p_building = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.5.2",
            state=Playable.State.BUILDING,
        )

        out = StringIO()
        call_command("regenerate_playables", dry_run=True, stdout=out)
        output = out.getvalue()
        self.assertIn("0 playables to regenerate", output)
        self.assertIn("1 playable(s) skipped in BUILDING state", output)

        out_forced = StringIO()
        call_command(
            "regenerate_playables",
            include_building=True,
            dry_run=True,
            stdout=out_forced,
        )
        self.assertIn(
            f"#{p_building.pk}: Test Adventure", out_forced.getvalue()
        )

    @patch("play.management.commands.regenerate_playables.generate_playable")
    def test_regenerate_synchronous(self, mock_generate: MagicMock) -> None:
        playable = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.4.0",
            state=Playable.State.READY,
        )

        out = StringIO()
        call_command("regenerate_playables", no_color=True, stdout=out)
        output = out.getvalue()

        self.assertIn(
            f"Regenerating #{playable.pk} "
            "(Test Adventure, instead_em v3.5.2)... OK",
            output,
        )
        self.assertIn("Regeneration complete: 1 succeeded, 0 failed.", output)

        playable.refresh_from_db()
        self.assertEqual(playable.template_version, "3.5.2")
        mock_generate.assert_called_once_with(playable.pk)

    @patch(
        "play.management.commands.regenerate_playables.generate_playable.delay"
    )
    def test_regenerate_async(self, mock_delay: MagicMock) -> None:
        playable = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.4.0",
            state=Playable.State.READY,
        )

        out = StringIO()
        call_command("regenerate_playables", run_async=True, stdout=out)
        output = out.getvalue()

        self.assertIn(
            f"Queued #{playable.pk} (Test Adventure, instead_em v3.5.2)",
            output,
        )
        self.assertIn("Regeneration complete: 1 succeeded, 0 failed.", output)

        playable.refresh_from_db()
        self.assertEqual(playable.template_version, "3.5.2")
        self.assertEqual(playable.state, Playable.State.PENDING)
        mock_delay.assert_called_once_with(playable.pk)

    @patch("play.management.commands.regenerate_playables.generate_playable")
    def test_regenerate_failure_handled(
        self, mock_generate: MagicMock
    ) -> None:
        mock_generate.side_effect = RuntimeError("Asset missing")
        playable = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.4.0",
            state=Playable.State.READY,
        )

        out = StringIO()
        call_command("regenerate_playables", no_color=True, stdout=out)
        output = out.getvalue()

        self.assertIn(f"Regenerating #{playable.pk}", output)
        self.assertIn("FAILED: Asset missing", output)
        self.assertIn("Regeneration complete: 0 succeeded, 1 failed.", output)
