import hashlib
import io
import json
import shutil
import unittest
from unittest.mock import patch

import updater


class UpdaterTests(unittest.TestCase):
    def test_version_comparison_and_rejects_prerelease(self):
        self.assertGreater(updater.version_tuple("v1.1.0"), updater.version_tuple("1.0.9"))
        with self.assertRaises(ValueError):
            updater.version_tuple("v1.2.0-beta")

    def test_release_requires_assets_from_own_repository(self):
        base = "https://github.com/Sweeney817/-/releases/download/v1.0.1/"
        release = {"tag_name": "v1.0.1", "assets": [
            {"name": updater.EXE_NAME, "browser_download_url": base + updater.EXE_NAME, "size": 3},
            {"name": updater.HASH_NAME, "browser_download_url": base + updater.HASH_NAME},
        ]}
        with patch.object(updater, "APP_VERSION", "1.0.0"), patch.object(updater, "read_url", return_value=json.dumps(release).encode()):
            self.assertEqual(updater.release_info()["size"], 3)
        release["assets"][0]["browser_download_url"] = "https://example.com/evil.exe"
        with patch.object(updater, "APP_VERSION", "1.0.0"), patch.object(updater, "read_url", return_value=json.dumps(release).encode()):
            with self.assertRaises(ValueError):
                updater.release_info()

    def test_older_and_prerelease_versions_are_not_installed(self):
        for release in ({"tag_name": "v0.9.0"}, {"tag_name": "v2.0.0", "prerelease": True}):
            with patch.object(updater, "read_url", return_value=json.dumps(release).encode()):
                self.assertIsNone(updater.release_info())

    def test_download_verifies_hash_and_size(self):
        contents = b"new executable"
        checksum = hashlib.sha256(contents).hexdigest().encode() + b"  OrangeCatDesktopPet.exe"
        info = {"hash": "https://github.com/hash", "exe": "https://github.com/exe", "size": len(contents)}
        with patch.object(updater, "read_url", return_value=checksum), patch.object(updater, "urlopen", return_value=io.BytesIO(contents)):
            result = updater.download_release(info)
            try:
                self.assertEqual(result.read_bytes(), contents)
            finally:
                shutil.rmtree(result.parent)
        with patch.object(updater, "read_url", return_value=b"0" * 64), patch.object(updater, "urlopen", return_value=io.BytesIO(contents)):
            with self.assertRaisesRegex(ValueError, "SHA256"):
                updater.download_release(info)

    def test_download_progress_reports_actual_bytes(self):
        contents = b'x' * (1024 * 1024 + 25)
        checksum = hashlib.sha256(contents).hexdigest().encode()
        info = {'hash': 'https://github.com/hash', 'exe': 'https://github.com/exe', 'size': len(contents)}
        progress = []
        with patch.object(updater, 'read_url', return_value=checksum), patch.object(updater, 'urlopen', return_value=io.BytesIO(contents)):
            result = updater.download_release(info, lambda done, total: progress.append((done, total)))
            try:
                self.assertEqual(progress, [(1024 * 1024, len(contents)), (len(contents), len(contents))])
            finally:
                shutil.rmtree(result.parent)
        info["size"] -= 1
        with patch.object(updater, "read_url", return_value=checksum), patch.object(updater, "urlopen", return_value=io.BytesIO(contents)):
            with self.assertRaises(ValueError):
                updater.download_release(info)


if __name__ == "__main__":
    unittest.main()
