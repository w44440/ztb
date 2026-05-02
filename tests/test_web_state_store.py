import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from web_state_store import StateStoreConfigError, StateStoreError
from web_state_store.jygs import download_state, ensure_state, get_state_path, upload_state
from web_state_store.s3 import S3Config, S3StateClient


class WebStateStoreTest(unittest.TestCase):
    def test_get_state_path_defaults_under_data_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir) / "data"
            with patch.dict(os.environ, {"ZTB_DATA_ROOT": str(data_root)}, clear=True):
                self.assertEqual(get_state_path(), data_root / "auth" / "jygs_storage_state.json")

    def test_get_state_path_allows_explicit_override(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "state.json"
            with patch.dict(os.environ, {"ZTB_JYGS_AUTH_STATE_PATH": str(state_path)}, clear=True):
                self.assertEqual(get_state_path(), state_path)

    def test_download_requires_s3_config(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(StateStoreConfigError):
                download_state()

    def test_ensure_state_downloads_then_checks(self):
        state_path = Path("/tmp/state.json")
        with (
            patch("web_state_store.jygs.download_state", return_value=state_path) as download,
            patch("web_state_store.jygs.check_state") as check,
        ):
            self.assertEqual(ensure_state(), state_path)

        download.assert_called_once_with("jygs")
        check.assert_called_once_with("jygs", path=state_path)

    def test_upload_checks_before_sending_to_s3(self):
        client = Mock()
        with (
            patch("web_state_store.jygs.check_state") as check,
            patch("web_state_store.jygs.S3Config.from_env", return_value=Mock()),
            patch("web_state_store.jygs.S3StateClient", return_value=client),
        ):
            upload_state(path=Path("/tmp/state.json"))

        check.assert_called_once_with("jygs", path=Path("/tmp/state.json"))
        client.upload_file.assert_called_once_with(Path("/tmp/state.json"))

    def test_rejects_unsupported_site(self):
        with self.assertRaises(StateStoreError):
            ensure_state("other")

    def test_s3_client_uses_boto3_r2_configuration(self):
        boto_client = Mock()
        config = S3Config(
            endpoint="abc.r2.cloudflarestorage.com",
            access_key="key",
            secret_key="secret",
            bucket="ztb",
            object_key="jygs_state.json",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "state.json"
            state_path.write_text("{}", encoding="utf-8")
            with patch("web_state_store.s3.boto3.client", return_value=boto_client) as boto3_client:
                client = S3StateClient(config)
                client.upload_file(state_path)

        boto3_client.assert_called_once_with(
            service_name="s3",
            endpoint_url="https://abc.r2.cloudflarestorage.com",
            aws_access_key_id="key",
            aws_secret_access_key="secret",
            region_name="auto",
        )
        boto_client.upload_file.assert_called_once_with(
            str(state_path), "ztb", "jygs_state.json"
        )

    def test_s3_config_uses_fixed_jygs_object_key(self):
        env = {
            "ZTB_STATE_S3_ENDPOINT": "https://abc.r2.cloudflarestorage.com",
            "ZTB_STATE_S3_ACCESS_KEY": "key",
            "ZTB_STATE_S3_SECRET_KEY": "secret",
            "ZTB_STATE_S3_BUCKET": "ztb",
            "ZTB_STATE_S3_OBJECT_KEY": "ignored.json",
            "ZTB_STATE_S3_REGION": "ignored",
        }
        with patch.dict(os.environ, env, clear=True):
            config = S3Config.from_env("jygs_state.json")

        self.assertEqual(config.object_key, "jygs_state.json")
        self.assertEqual(config.region, "auto")


if __name__ == "__main__":
    unittest.main()
