"""Tests for keel_runtime.config's precedence: flags > env > file (spec FR-026)."""
import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from keel_runtime import config as config_module

_ENV_KEYS = (
    "KEEL_BASE_URL",
    "KEEL_EXECUTOR",
    "KEEL_HOME",
    "KEEL_CREDENTIAL_BACKEND",
    "KEEL_SCRIPT",
    "KEEL_JOB_BUDGET_USD",
    "KEEL_JOB_MAX_TURNS",
    "KEEL_JOB_TIMEOUT_SECONDS",
)


class ConfigPrecedenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._env_backup = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        self._tmp.cleanup()
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _args(self, **overrides):
        base = dict(
            base_url=None,
            executor=None,
            home=str(self.home),
            credential_backend=None,
            no_browser=False,
            script=None,
        )
        base.update(overrides)
        return Namespace(**base)

    def test_flag_wins_over_env_and_file(self):
        (self.home / "config.json").write_text(json.dumps({"base_url": "http://file"}))
        os.environ["KEEL_BASE_URL"] = "http://env"
        config = config_module.load(self._args(base_url="http://flag"))
        self.assertEqual(config.base_url, "http://flag")

    def test_env_wins_over_file(self):
        (self.home / "config.json").write_text(json.dumps({"base_url": "http://file"}))
        os.environ["KEEL_BASE_URL"] = "http://env"
        config = config_module.load(self._args())
        self.assertEqual(config.base_url, "http://env")

    def test_file_used_when_no_flag_or_env(self):
        (self.home / "config.json").write_text(json.dumps({"base_url": "http://file"}))
        config = config_module.load(self._args())
        self.assertEqual(config.base_url, "http://file")

    def test_missing_base_url_exits(self):
        with self.assertRaises(SystemExit):
            config_module.load(self._args())

    def test_default_home_is_dot_keel_when_nothing_names_one(self):
        args = self._args(home=None, base_url="http://flag")
        config = config_module.load(args)
        self.assertEqual(config.home, Path.home() / ".keel")

    def test_executor_defaults_to_claude_code(self):
        config = config_module.load(self._args(base_url="http://flag"))
        self.assertEqual(config.executor, "claude-code")

    def test_credential_backend_defaults_to_auto(self):
        config = config_module.load(self._args(base_url="http://flag"))
        self.assertEqual(config.credential_backend, "auto")

    def test_no_browser_flag_sets_open_browser_false(self):
        config = config_module.load(self._args(base_url="http://flag", no_browser=True))
        self.assertFalse(config.open_browser)

    def test_open_browser_defaults_true(self):
        config = config_module.load(self._args(base_url="http://flag"))
        self.assertTrue(config.open_browser)

    def test_script_defaults_to_none(self):
        config = config_module.load(self._args(base_url="http://flag"))
        self.assertIsNone(config.script_path)

    def test_script_flag_wins_over_env(self):
        os.environ["KEEL_SCRIPT"] = "/env/script.json"
        config = config_module.load(
            self._args(base_url="http://flag", script="/flag/script.json")
        )
        self.assertEqual(config.script_path, "/flag/script.json")

    def test_script_env_wins_over_file(self):
        (self.home / "config.json").write_text(
            json.dumps({"base_url": "http://flag", "script": "/file/script.json"})
        )
        os.environ["KEEL_SCRIPT"] = "/env/script.json"
        config = config_module.load(self._args())
        self.assertEqual(config.script_path, "/env/script.json")

    # spec 002-words-are-words FR-007, amended by FR-009 -----------------------------

    def test_job_budget_usd_defaults_to_a_dollar(self):
        config = config_module.load(self._args(base_url="http://flag"))
        self.assertEqual(config.job_budget_usd, 1.00)

    def test_job_max_turns_defaults_to_six(self):
        config = config_module.load(self._args(base_url="http://flag"))
        self.assertEqual(config.job_max_turns, 6)

    def test_job_budget_usd_env_wins_over_file(self):
        (self.home / "config.json").write_text(
            json.dumps({"base_url": "http://flag", "budget_usd": 0.5})
        )
        os.environ["KEEL_JOB_BUDGET_USD"] = "0.75"
        config = config_module.load(self._args())
        self.assertEqual(config.job_budget_usd, 0.75)

    def test_job_budget_usd_file_used_when_no_env(self):
        (self.home / "config.json").write_text(
            json.dumps({"base_url": "http://flag", "budget_usd": 0.5})
        )
        config = config_module.load(self._args())
        self.assertEqual(config.job_budget_usd, 0.5)

    def test_job_max_turns_env_wins_over_file(self):
        (self.home / "config.json").write_text(
            json.dumps({"base_url": "http://flag", "max_turns": 3})
        )
        os.environ["KEEL_JOB_MAX_TURNS"] = "5"
        config = config_module.load(self._args())
        self.assertEqual(config.job_max_turns, 5)

    def test_job_max_turns_file_used_when_no_env(self):
        (self.home / "config.json").write_text(
            json.dumps({"base_url": "http://flag", "max_turns": 3})
        )
        config = config_module.load(self._args())
        self.assertEqual(config.job_max_turns, 3)

    # The wall clock a closed `claude` invocation is given ---------------------------
    # Measured rather than guessed: keel-e2e-eval's instruction eval found every
    # `*_ASSUMPTIONS` job running 81-120s against the old hard-coded 120, six of
    # twenty-one hitting it, and the slowest survivor eleven seconds clear.

    def test_job_timeout_seconds_defaults_to_five_minutes(self):
        config = config_module.load(self._args(base_url="http://flag"))
        self.assertEqual(config.job_timeout_seconds, 300.0)

    def test_job_timeout_seconds_env_wins_over_file(self):
        (self.home / "config.json").write_text(
            json.dumps({"base_url": "http://flag", "job_timeout_seconds": 200})
        )
        os.environ["KEEL_JOB_TIMEOUT_SECONDS"] = "450"
        config = config_module.load(self._args())
        self.assertEqual(config.job_timeout_seconds, 450.0)

    def test_job_timeout_seconds_file_used_when_no_env(self):
        (self.home / "config.json").write_text(
            json.dumps({"base_url": "http://flag", "job_timeout_seconds": 200})
        )
        config = config_module.load(self._args())
        self.assertEqual(config.job_timeout_seconds, 200.0)

    def test_an_unparseable_job_timeout_override_falls_through_to_the_default(self):
        os.environ["KEEL_JOB_TIMEOUT_SECONDS"] = "as long as it takes"
        config = config_module.load(self._args(base_url="http://flag"))
        self.assertEqual(config.job_timeout_seconds, 300.0)


if __name__ == "__main__":
    unittest.main()
