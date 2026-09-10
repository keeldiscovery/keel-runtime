"""Tests for keel_runtime.credential_store's file backend (spec FR-025)."""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from keel_runtime.credential_store import Credential, CredentialStore


class CredentialStoreFileBackendTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_with_nothing_stored_is_none(self):
        store = CredentialStore(self.home, backend="file")
        self.assertIsNone(store.load())

    def test_round_trip(self):
        store = CredentialStore(self.home, backend="file")
        credential = Credential(
            access_token="a", refresh_token="r", expires_at=123.0, scope=["s1"]
        )
        store.save(credential)

        loaded = store.load()
        self.assertEqual(loaded.access_token, "a")
        self.assertEqual(loaded.refresh_token, "r")
        self.assertEqual(loaded.expires_at, 123.0)
        self.assertEqual(loaded.scope, ["s1"])

    @unittest.skipIf(
        sys.platform == "win32",
        "NTFS has no POSIX permission bits: os.chmod(0o600) does not restrict the file there, "
        "and credential_store.save's own chmod is documented best-effort for exactly this case",
    )
    def test_file_mode_is_0600(self):
        store = CredentialStore(self.home, backend="file")
        store.save(Credential(access_token="a", refresh_token="r", expires_at=1.0, scope=[]))
        mode = stat.S_IMODE(os.stat(self.home / "credentials.json").st_mode)
        self.assertEqual(mode, 0o600)

    def test_clear_removes_the_file(self):
        store = CredentialStore(self.home, backend="file")
        store.save(Credential(access_token="a", refresh_token="r", expires_at=1.0, scope=[]))
        store.clear()
        self.assertIsNone(store.load())
        self.assertFalse((self.home / "credentials.json").exists())

    def test_clear_on_missing_file_is_a_no_op(self):
        store = CredentialStore(self.home, backend="file")
        store.clear()  # must not raise

    def test_backend_file_forces_file_even_if_keyring_were_importable(self):
        store = CredentialStore(self.home, backend="file")
        self.assertFalse(store._use_keyring)


if __name__ == "__main__":
    unittest.main()
