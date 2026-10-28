import hashlib
import io
import shutil
import unittest
from unittest.mock import patch

import updater


class UpdaterTests(unittest.TestCase):
    def test_version_comparison_and_rejects_prerelease(self):
        self.assertGreater(updater.version_tuple("v1.1.0"), updater.version_tuple("1.0.9"))
        with self.assertRaises(ValueError):
            updater.version_tuple("v1.2.0-beta")

    def test_latest_release_redirect_and_asset_size(self):
        from unittest.mock import MagicMock
        release = MagicMock()
        release.__enter__.return_value.geturl.return_value = "https://github.com/Sweeney817/-/releases/tag/v1.0.1"
        asset = MagicMock()
        asset.__enter__.return_value.headers = {"Content-Length": "3"}
        with patch.object(updater, "APP_VERSION", "1.0.0"), patch.object(updater, "urlopen", side_effect=[release, asset]) as urlopen:
            info = updater.release_info()
            self.assertEqual(info["size"], 3)
            self.assertEqual(info["exe"], "https://github.com/Sweeney817/-/releases/download/v1.0.1/OrangeCatDesktopPet.exe")
            self.assertTrue(all(call.args[0].get_method() == "HEAD" for call in urlopen.call_args_list))

    def test_invalid_redirect_rejected_and_old_release_ignored(self):
        from unittest.mock import MagicMock
        for url in ("https://example.com/Sweeney817/-/releases/tag/v2.0.0", "https://github.com/Sweeney817/-/releases/tag/v2.0.0-beta"):
            response = MagicMock()
            response.__enter__.return_value.geturl.return_value = url
            with patch.object(updater, "urlopen", return_value=response), self.assertRaises(ValueError):
                updater.release_info()
        response = MagicMock()
        response.__enter__.return_value.geturl.return_value = "https://github.com/Sweeney817/-/releases/tag/v0.9.0"
        with patch.object(updater, "APP_VERSION", "1.0.0"), patch.object(updater, "urlopen", return_value=response):
            self.assertIsNone(updater.release_info())

    def test_invalid_size_rejected(self):
        from unittest.mock import MagicMock
        release = MagicMock()
        release.__enter__.return_value.geturl.return_value = "https://github.com/Sweeney817/-/releases/tag/v2.0.0"
        for length in ("", "0", str(updater.MAX_DOWNLOAD + 1)):
            asset = MagicMock()
            asset.__enter__.return_value.headers = {"Content-Length": length}
            with patch.object(updater, "APP_VERSION", "1.0.0"), patch.object(updater, "urlopen", side_effect=[release, asset]), self.assertRaises(ValueError):
                updater.release_info()

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
