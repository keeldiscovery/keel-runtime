"""The home follows the address (spec `004-shipped-runtime` FR-007/FR-008; design
`keel-skill-design.md` §6.3, invariant E-1).

`~/.keel` was one directory for every Keel, and keel-connect-playground set `KEEL_HOME` by hand so
a test credential was never presented to production. The moment a human forgot, one Keel was handed
another's token and the failure was a 401 that named no cause. The home is now derived from the
*resolved* base URL, and `KEEL_HOME`/`--home` are the only way to make two Keels share one.

The slug table below is the contract: every row of it is asserted here.
"""
import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from keel_runtime import config as config_module

# resolved base URL -> (slug under `~/.keel/`, `environment`). `None` as a slug means "no slug can
# be derived; the home falls back to `~/.keel` itself".
SLUG_TABLE = (
    ("http://localhost:18081", "localhost-18081", "localhost:18081"),
    ("http://localhost:18080", "localhost-18080", "localhost:18080"),
    ("http://127.0.0.1:1", "127.0.0.1-1", "127.0.0.1:1"),
    ("https://cloud.keel.example", "cloud.keel.example", "cloud.keel.example"),
    # The scheme is in neither column: two base URLs differing only by scheme are one Keel with a
    # misconfiguration, not two (§6.3). Case and path are not in either column for the same reason.
    ("http://cloud.keel.example", "cloud.keel.example", "cloud.keel.example"),
    ("https://Cloud.Keel.Example/v2/", "cloud.keel.example", "cloud.keel.example"),
    # A port that is *stated* is kept, even a default one -- the derivation never guesses.
    ("https://cloud.keel.example:443", "cloud.keel.example-443", "cloud.keel.example:443"),
    # No userinfo, no path, no query reaches the filesystem.
    ("http://u:pw@example.com:8080/v2?x=1", "example.com-8080", "example.com:8080"),
    # Outside `[a-z0-9.-]` -> `-`, in the slug only: the environment is the address as written.
    ("https://keel_cloud.internal", "keel-cloud.internal", "keel_cloud.internal"),
    ("http://[::1]:8080", "--1-8080", "[::1]:8080"),
    # `~/.keel/bin/` is Keel's own (§10.4).
    ("http://bin", "bin-keel", "bin"),
    # A human who typed no scheme meant a host and a port, and gets the same slug as the URL form.
    ("localhost:18081", "localhost-18081", "localhost:18081"),
    # Nothing that could name a directory: no slug, and no environment either.
    ("", None, None),
    (".", None, None),
    ("..", None, None),
    ("http://", None, None),
)


class HostSlugTest(unittest.TestCase):
    def test_the_slug_table(self):
        for base_url, expected_slug, _environment in SLUG_TABLE:
            with self.subTest(base_url=base_url):
                self.assertEqual(config_module.host_slug(base_url), expected_slug)

    def test_the_environment_table(self):
        for base_url, _slug, expected_environment in SLUG_TABLE:
            with self.subTest(base_url=base_url):
                self.assertEqual(config_module.environment_for(base_url), expected_environment)

    def test_a_slug_never_leaves_the_safe_character_class(self):
        for base_url, expected_slug, _environment in SLUG_TABLE:
            if expected_slug is None:
                continue
            with self.subTest(base_url=base_url):
                self.assertRegex(expected_slug, r"^[a-z0-9.-]+$")
                self.assertNotIn(expected_slug, (".", ".."))

    def test_the_built_in_default_is_named_cloud_and_still_gets_its_own_hosts_home(self):
        with mock.patch.object(config_module, "CLOUD_BASE_URL", "https://cloud.keel.example"):
            self.assertEqual(config_module.environment_for("https://cloud.keel.example"), "cloud")
            self.assertEqual(config_module.host_slug("https://cloud.keel.example"),
                             "cloud.keel.example")

    def test_the_real_cloud_default_slugs_to_app_keeldiscovery_com(self):
        """Since design §13 step 8: no mocking, the constant's real value."""
        self.assertEqual(config_module.CLOUD_BASE_URL, "https://app.keeldiscovery.com")
        self.assertEqual(config_module.environment_for(config_module.CLOUD_BASE_URL), "cloud")
        self.assertEqual(
            config_module.host_slug(config_module.CLOUD_BASE_URL), "app.keeldiscovery.com"
        )

    def test_none_is_not_an_address(self):
        self.assertIsNone(config_module.host_slug(None))
        self.assertIsNone(config_module.environment_for(None))


class DerivedHomeTest(unittest.TestCase):
    """The two phases of FR-007, driven through `load_status_config` -- which is the resolution
    `status` uses and therefore the one a caller sees.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fake_home = Path(self._tmp.name)
        self._env = mock.patch.dict(
            os.environ,
            {"HOME": str(self.fake_home), "USERPROFILE": str(self.fake_home)},
        )
        self._env.start()
        for key in ("KEEL_HOME", "KEEL_BASE_URL", "KEEL_EXECUTOR"):
            os.environ.pop(key, None)

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _args(self, **overrides):
        base = dict(home=None, base_url=None, executor=None)
        base.update(overrides)
        return Namespace(**base)

    def test_a_base_url_from_the_environment_derives_the_home(self):
        os.environ["KEEL_BASE_URL"] = "http://localhost:18081"
        resolved = config_module.load_status_config(self._args())
        self.assertEqual(resolved.home, self.fake_home / ".keel" / "localhost-18081")
        self.assertEqual(resolved.environment, "localhost:18081")

    def test_two_base_urls_from_one_home_never_share_a_directory(self):
        """E-1, without the live approval the founder walks (A-9)."""
        homes = set()
        for base_url in ("http://localhost:18081", "http://localhost:18080"):
            resolved = config_module.load_status_config(self._args(base_url=base_url))
            resolved.home.mkdir(parents=True, exist_ok=True)
            (resolved.home / "credentials.json").write_text(json.dumps({"for": base_url}))
            homes.add(resolved.home)
        self.assertEqual(len(homes), 2)
        first = self.fake_home / ".keel" / "localhost-18081" / "credentials.json"
        self.assertEqual(json.loads(first.read_text())["for"], "http://localhost:18081")

    def test_a_local_and_a_cloud_base_url_never_share_a_home(self):
        with mock.patch.object(config_module, "CLOUD_BASE_URL", "https://cloud.keel.example"):
            cloud = config_module.load_status_config(self._args())
            local = config_module.load_status_config(
                self._args(base_url="http://localhost:18081")
            )
            # `environment` is derived on read, so it is read while the constant has its value.
            self.assertEqual(cloud.environment, "cloud")
            self.assertEqual(local.environment, "localhost:18081")
        self.assertEqual(cloud.home, self.fake_home / ".keel" / "cloud.keel.example")
        self.assertEqual(local.home, self.fake_home / ".keel" / "localhost-18081")
        self.assertNotEqual(cloud.home, local.home)

    def test_the_home_flag_wins_outright(self):
        override = self.fake_home / "chosen"
        resolved = config_module.load_status_config(
            self._args(home=str(override), base_url="http://localhost:18081")
        )
        self.assertEqual(resolved.home, override)

    def test_keel_home_wins_outright(self):
        override = self.fake_home / "chosen"
        os.environ["KEEL_HOME"] = str(override)
        os.environ["KEEL_BASE_URL"] = "http://localhost:18081"
        resolved = config_module.load_status_config(self._args())
        self.assertEqual(resolved.home, override)

    def test_nothing_resolves_at_all_reaches_the_cloud_default(self):
        """Since design §13 step 8, `CLOUD_BASE_URL` is a real address and phase 2 resolves to it
        before phase 3 is ever reached -- so "nothing configured" now derives a home under it
        rather than falling back to `~/.keel` itself.
        """
        resolved = config_module.load_status_config(self._args())
        self.assertEqual(resolved.home, self.fake_home / ".keel" / "app.keeldiscovery.com")
        self.assertEqual(resolved.base_url, "https://app.keeldiscovery.com")
        self.assertEqual(resolved.environment, "cloud")

    def test_nothing_resolves_at_all_and_the_home_is_todays_root_when_the_default_is_unset(self):
        """Phase 3 of FR-007, exercised the way it now can be: with `CLOUD_BASE_URL` cleared, as
        it shipped before design §13 step 8.
        """
        with mock.patch.object(config_module, "CLOUD_BASE_URL", ""):
            resolved = config_module.load_status_config(self._args())
        self.assertEqual(resolved.home, self.fake_home / ".keel")
        self.assertIsNone(resolved.base_url)
        self.assertIsNone(resolved.environment)

    def test_the_root_config_file_may_still_name_a_base_url_when_nothing_else_does(self):
        """Phase 3 of FR-007: today's one working branch, reachable now only with the cloud
        default cleared -- real installs resolve `CLOUD_BASE_URL` before this file is consulted.
        """
        root = self.fake_home / ".keel"
        root.mkdir(parents=True)
        (root / "config.json").write_text(json.dumps({"base_url": "http://localhost:18081"}))
        with mock.patch.object(config_module, "CLOUD_BASE_URL", ""):
            resolved = config_module.load_status_config(self._args())
        self.assertEqual(resolved.home, root)
        self.assertEqual(resolved.base_url, "http://localhost:18081")
        self.assertEqual(resolved.environment, "localhost:18081")

    def test_a_derived_homes_config_file_may_not_rename_its_own_keel(self):
        """Phase 2 of FR-007: the file supplies every key but `base_url`, which named the home."""
        derived = self.fake_home / ".keel" / "localhost-18081"
        derived.mkdir(parents=True)
        (derived / "config.json").write_text(
            json.dumps({"base_url": "http://somewhere.else", "executor": "scripted"})
        )
        os.environ["KEEL_BASE_URL"] = "http://localhost:18081"
        resolved = config_module.load_status_config(self._args())
        self.assertEqual(resolved.home, derived)
        self.assertEqual(resolved.base_url, "http://localhost:18081")
        self.assertEqual(resolved.executor, "scripted")

    def test_an_explicit_homes_config_file_still_names_the_base_url(self):
        override = self.fake_home / "chosen"
        override.mkdir(parents=True)
        (override / "config.json").write_text(json.dumps({"base_url": "http://localhost:18081"}))
        resolved = config_module.load_status_config(self._args(home=str(override)))
        self.assertEqual(resolved.base_url, "http://localhost:18081")

    def test_an_unparseable_base_url_falls_back_to_the_root_rather_than_failing(self):
        os.environ["KEEL_BASE_URL"] = "http://["
        resolved = config_module.load_status_config(self._args())
        self.assertEqual(resolved.home, self.fake_home / ".keel")
        self.assertIsNone(resolved.environment)


if __name__ == "__main__":
    unittest.main()
