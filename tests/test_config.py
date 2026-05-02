import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ztb_fetcher.config as config_module
from ztb_fetcher.config import Config


class ConfigTest(unittest.TestCase):
    def _reload_config_module(self):
        return importlib.reload(config_module)

    def test_environment_variable_has_highest_priority(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_dir = tmp_path / ".ztb"
            config_dir.mkdir()
            config_file = config_dir / "config.json"
            config_file.write_text(
                json.dumps({"kimi_model": "from-config"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with (
                patch.object(Config, "CONFIG_DIR", config_dir),
                patch.object(Config, "CONFIG_FILE", config_file),
                patch.dict(os.environ, {"ZTB_KIMI_MODEL": "from-env"}, clear=True),
            ):
                config = Config()
                self.assertEqual(config.get("kimi_model"), "from-env")

    def test_falls_back_to_config_file_when_environment_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_dir = tmp_path / ".ztb"
            config_dir.mkdir()
            config_file = config_dir / "config.json"
            config_file.write_text(
                json.dumps({"kimi_model": "from-config"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with (
                patch.object(Config, "CONFIG_DIR", config_dir),
                patch.object(Config, "CONFIG_FILE", config_file),
                patch.dict(os.environ, {}, clear=True),
            ):
                config = Config()

            self.assertEqual(config.get("kimi_model"), "from-config")

    def test_falls_back_to_default_when_all_sources_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_dir = tmp_path / ".ztb"
            config_dir.mkdir()
            config_file = config_dir / "config.json"
            config_file.write_text("{}", encoding="utf-8")

            with (
                patch.object(Config, "CONFIG_DIR", config_dir),
                patch.object(Config, "CONFIG_FILE", config_file),
                patch.dict(os.environ, {}, clear=True),
            ):
                config = Config()

            self.assertEqual(config.get("kimi_model", "kimi-k2.5"), "kimi-k2.5")

    def test_default_data_root_uses_hdd_mount(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            original_home = os.environ.get("HOME")

            try:
                with patch.dict(os.environ, {"HOME": str(Path(tmp_dir) / "home")}, clear=True):
                    module = self._reload_config_module()

                self.assertEqual(module.DATA_ROOT, Path("/data/ops-data/ztb"))
                self.assertEqual(module.DUCKDB_PATH, Path("/data/ops-data/ztb/zt_data.duckdb"))
                self.assertEqual(module.LOG_FILE, Path("/data/ops-data/ztb/logs/ztb.log"))
            finally:
                if original_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = original_home
                self._reload_config_module()

    def test_status_file_uses_data_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir) / "home"
            data_root = Path(tmp_dir) / "data"
            original_home = os.environ.get("HOME")

            try:
                with patch.dict(
                    os.environ,
                    {"HOME": str(home), "ZTB_DATA_ROOT": str(data_root)},
                    clear=True,
                ):
                    module = self._reload_config_module()

                self.assertEqual(module.STATUS_FILE, data_root / "last_run.json")
            finally:
                if original_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = original_home
                self._reload_config_module()

    def test_environment_variable_overrides_data_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir) / "hdd-data"
            original_home = os.environ.get("HOME")
            env = {"ZTB_DATA_ROOT": str(data_root), "HOME": str(Path(tmp_dir) / "home")}

            try:
                with patch.dict(os.environ, env, clear=True):
                    module = self._reload_config_module()

                self.assertEqual(module.DATA_ROOT, data_root)
                self.assertEqual(module.DUCKDB_PATH, data_root / "zt_data.duckdb")
                self.assertEqual(module.REPORTS_DIR, data_root / "reports")
            finally:
                if original_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = original_home
                self._reload_config_module()

    def test_config_file_data_root_is_used_when_environment_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            home_dir = tmp_path / "home"
            config_dir = home_dir / ".ztb"
            config_dir.mkdir(parents=True)
            data_root = tmp_path / "configured-data"
            (config_dir / "config.json").write_text(
                json.dumps({"data_root": str(data_root)}, ensure_ascii=False),
                encoding="utf-8",
            )
            original_home = os.environ.get("HOME")

            try:
                with patch.dict(os.environ, {"HOME": str(home_dir)}, clear=True):
                    module = self._reload_config_module()

                self.assertEqual(module.DATA_ROOT, data_root)
                self.assertEqual(module.JYGS_CACHE_DIR, data_root / "jygs_cache")
                self.assertEqual(module.THS_OCR_CACHE_DIR, data_root / "ths_ocr_cache")
            finally:
                if original_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = original_home
                self._reload_config_module()


if __name__ == "__main__":
    unittest.main()
