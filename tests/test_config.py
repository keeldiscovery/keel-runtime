"""Tests for keel_runtime.config's precedence: flags > env > file (spec FR-026)."""
import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from keel_runtime import config as config_module

_ENV_KEYS = (
    "KEEL_BASE_URL",
    "KEEL_EXECUTOR",
    "KEEL_HOME",
    "KEEL_CREDENTIAL_BACKEND",
    "KEEL_SCRIPT",
    "KEEL_CONTEXT_KEYS",
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
            context_keys=None,
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

    def test_the_home_follows_the_address_when_nothing_names_one(self):
        """Was `test_default_home_is_dot_keel_when_nothing_names_one`, and asserted
        `~/.keel` for every Keel. Since spec `004-shipped-runtime` (design §6.3) the home is
        derived from the resolved base URL; `~/.keel` itself survives only for the case where
        nothing resolves at all, which `tests/test_home_derivation.py` covers.
        """
        args = self._args(home=None, base_url="http://localhost:18081")
        config = config_module.load(args)
        self.assertEqual(config.home, Path.home() / ".keel" / "localhost-18081")

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

    # spec 001-scripted-executor AMENDMENT-measured-beliefs RT-001 --------------------

    def test_context_keys_defaults_to_none_meaning_the_bundled_copy(self):
        config = config_module.load(self._args(base_url="http://flag"))
        self.assertIsNone(config.context_keys_path)

    def test_context_keys_flag_wins_over_env(self):
        os.environ["KEEL_CONTEXT_KEYS"] = "/env/context-keys.json"
        config = config_module.load(
            self._args(base_url="http://flag", context_keys="/flag/context-keys.json")
        )
        self.assertEqual(config.context_keys_path, "/flag/context-keys.json")

    def test_context_keys_env_wins_over_file(self):
        (self.home / "config.json").write_text(
            json.dumps({"base_url": "http://flag", "context_keys": "/file/context-keys.json"})
        )
        os.environ["KEEL_CONTEXT_KEYS"] = "/env/context-keys.json"
        config = config_module.load(self._args())
        self.assertEqual(config.context_keys_path, "/env/context-keys.json")

    def test_context_keys_file_is_read_when_nothing_else_sets_it(self):
        (self.home / "config.json").write_text(
            json.dumps({"base_url": "http://flag", "context_keys": "/file/context-keys.json"})
        )
        config = config_module.load(self._args())
        self.assertEqual(config.context_keys_path, "/file/context-keys.json")

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



class CloudDefaultTest(unittest.TestCase):
    """`CLOUD_BASE_URL` is the last term of the chain (spec `004-shipped-runtime` FR-006,
    invariant E-2): a flag, `KEEL_BASE_URL` or `$KEEL_HOME/config.json` always outranks it; when
    it has a value it is used *instead of* exiting; while it is the empty placeholder, behaviour
    is exactly today's, `SystemExit` and remedy included.
    """

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
            context_keys=None,
        )
        base.update(overrides)
        return Namespace(**base)

    def test_an_empty_constant_keeps_todays_exit_and_its_remedy(self):
        self.assertEqual(config_module.CLOUD_BASE_URL, "")
        with self.assertRaises(SystemExit) as raised:
            config_module.load(self._args())
        message = str(raised.exception)
        self.assertIn("--base-url", message)
        self.assertIn("KEEL_BASE_URL", message)
        self.assertIn("config.json", message)

    def test_a_constant_with_a_value_is_used_instead_of_exiting(self):
        with mock.patch.object(config_module, "CLOUD_BASE_URL", "https://cloud.keel.example"):
            config = config_module.load(self._args())
            self.assertEqual(config.base_url, "https://cloud.keel.example")
            self.assertEqual(config.environment, "cloud")

    def test_a_flag_outranks_the_constant(self):
        with mock.patch.object(config_module, "CLOUD_BASE_URL", "https://cloud.keel.example"):
            config = config_module.load(self._args(base_url="http://localhost:18081"))
            self.assertEqual(config.base_url, "http://localhost:18081")
            self.assertEqual(config.environment, "localhost:18081")

    def test_the_environment_variable_outranks_the_constant(self):
        os.environ["KEEL_BASE_URL"] = "http://localhost:18081"
        with mock.patch.object(config_module, "CLOUD_BASE_URL", "https://cloud.keel.example"):
            config = config_module.load(self._args())
            self.assertEqual(config.base_url, "http://localhost:18081")

    def test_the_file_config_outranks_the_constant(self):
        (self.home / "config.json").write_text(json.dumps({"base_url": "http://localhost:18081"}))
        with mock.patch.object(config_module, "CLOUD_BASE_URL", "https://cloud.keel.example"):
            config = config_module.load(self._args())
            self.assertEqual(config.base_url, "http://localhost:18081")

    def test_environment_is_null_when_nothing_resolves(self):
        status = config_module.load_status_config(self._args())
        self.assertIsNone(status.base_url)
        self.assertIsNone(status.environment)


if __name__ == "__main__":
    unittest.main()
