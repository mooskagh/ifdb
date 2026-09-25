"""Tests for scripts/deploy_plumbum.py CLI flags and non-interactive steps."""

import unittest
from unittest.mock import MagicMock, patch

from scripts import deploy_plumbum


class DeployPlumbumTestCase(unittest.TestCase):
    def test_message_interactive(self) -> None:
        step = deploy_plumbum.Message("test msg", "prompt")
        with patch("builtins.input", return_value="") as mock_input:
            res = step({"interactive": True})
            self.assertTrue(res)
            mock_input.assert_called_once_with("prompt")

    def test_message_non_interactive(self) -> None:
        step = deploy_plumbum.Message("test msg", "prompt")
        with patch("builtins.input") as mock_input:
            res = step({"interactive": False})
            self.assertTrue(res)
            mock_input.assert_not_called()

    def test_stop_timer_interactive(self) -> None:
        with patch("builtins.input", return_value="") as mock_input:
            res = deploy_plumbum.StopTimer({
                "interactive": True,
                "down-time": 100,
            })
            self.assertTrue(res)
            mock_input.assert_called_once_with("Press Enter to continue...")

    def test_stop_timer_non_interactive(self) -> None:
        with patch("builtins.input") as mock_input:
            res = deploy_plumbum.StopTimer({
                "interactive": False,
                "down-time": 100,
            })
            self.assertTrue(res)
            mock_input.assert_not_called()

    def test_loop_step_interactive_exits_on_n(self) -> None:
        func = MagicMock(return_value=True)
        func.__doc__ = "dummy func"
        step = deploy_plumbum.LoopStep(func, "prompt")
        with patch("builtins.input", return_value="n") as mock_input:
            res = step({"interactive": True})
            self.assertTrue(res)
            mock_input.assert_called_once_with("prompt (y/n): ")
            func.assert_not_called()

    def test_loop_step_non_interactive(self) -> None:
        func = MagicMock(return_value=True)
        func.__doc__ = "dummy func"
        step = deploy_plumbum.LoopStep(func, "prompt")
        with patch("builtins.input") as mock_input:
            res = step({"interactive": False})
            self.assertTrue(res)
            mock_input.assert_not_called()
            func.assert_not_called()

    def test_get_next_version_interactive(self) -> None:
        with (
            patch(
                "scripts.deploy_plumbum.GetCurrentVersion",
                return_value=(1, 2, 3),
            ),
            patch("builtins.input", return_value="2") as mock_input,
        ):
            ctx: dict[str, object] = {"interactive": True}
            res = deploy_plumbum.GetNextVersion(ctx)
            self.assertTrue(res)
            self.assertEqual(ctx["new-version"], "v1.03")
            mock_input.assert_called_once()

    def test_get_next_version_non_interactive(self) -> None:
        with (
            patch(
                "scripts.deploy_plumbum.GetCurrentVersion",
                return_value=(1, 2, 3),
            ),
            patch("builtins.input") as mock_input,
        ):
            ctx: dict[str, object] = {"interactive": False}
            res = deploy_plumbum.GetNextVersion(ctx)
            self.assertTrue(res)
            self.assertEqual(ctx["new-version"], "v1.02.4")
            mock_input.assert_not_called()

    def test_pipeline_maybe_load_state_interactive(self) -> None:
        p = deploy_plumbum.Pipeline()
        p.interactive = True
        with (
            patch("os.path.isfile", return_value=True),
            patch("builtins.input", return_value="n") as mock_input,
        ):
            p.MaybeLoadState()
            mock_input.assert_called_once()

    def test_pipeline_maybe_load_state_non_interactive(self) -> None:
        p = deploy_plumbum.Pipeline()
        p.interactive = False
        with (
            patch("os.path.isfile", return_value=True),
            patch("builtins.input") as mock_input,
        ):
            p.MaybeLoadState()
            mock_input.assert_not_called()

    def test_deploy_pipeline_staging_flag(self) -> None:
        recorded: list[deploy_plumbum.Pipeline] = []

        def fake_run(self_p: deploy_plumbum.Pipeline, cmd_name: str) -> None:
            recorded.append(self_p)

        # Default includes staging steps (46 steps total)
        with patch.object(deploy_plumbum.Pipeline, "Run", fake_run):
            deploy_plumbum.DeployApp.run(
                ["deploy_plumbum.py", "deploy"], exit=False
            )
            self.assertEqual(len(recorded), 1)
            self.assertEqual(len(recorded[0].steps), 46)
            self.assertTrue(recorded[0].interactive)

        recorded.clear()

        # --no-staging excludes staging steps (43 steps total)
        with patch.object(deploy_plumbum.Pipeline, "Run", fake_run):
            deploy_plumbum.DeployApp.run(
                ["deploy_plumbum.py", "deploy", "--no-staging"], exit=False
            )
            self.assertEqual(len(recorded), 1)
            self.assertEqual(len(recorded[0].steps), 43)

    def test_deploy_pipeline_interactive_flag(self) -> None:
        recorded: list[deploy_plumbum.Pipeline] = []

        def fake_run(self_p: deploy_plumbum.Pipeline, cmd_name: str) -> None:
            recorded.append(self_p)

        # --no-interactive sets interactive to False
        with patch.object(deploy_plumbum.Pipeline, "Run", fake_run):
            deploy_plumbum.DeployApp.run(
                ["deploy_plumbum.py", "deploy", "--no-interactive"], exit=False
            )
            self.assertEqual(len(recorded), 1)
            self.assertFalse(recorded[0].interactive)

    def test_deploy_pipeline_superhot_flag(self) -> None:
        recorded: list[deploy_plumbum.Pipeline] = []

        def fake_run(self_p: deploy_plumbum.Pipeline, cmd_name: str) -> None:
            recorded.append(self_p)

        with patch.object(deploy_plumbum.Pipeline, "Run", fake_run):
            deploy_plumbum.DeployApp.run(
                ["deploy_plumbum.py", "deploy", "--superhot"], exit=False
            )
            self.assertEqual(len(recorded), 1)
            step_docs = [s.__doc__ or "" for s in recorded[0].steps]
            self.assertFalse(any("pg_dump" in doc for doc in step_docs))

        recorded.clear()

        with patch.object(deploy_plumbum.Pipeline, "Run", fake_run):
            deploy_plumbum.DeployApp.run(
                ["deploy_plumbum.py", "deploy"], exit=False
            )
            self.assertEqual(len(recorded), 1)
            step_docs = [s.__doc__ or "" for s in recorded[0].steps]
            self.assertTrue(any("pg_dump" in doc for doc in step_docs))


if __name__ == "__main__":
    unittest.main()
