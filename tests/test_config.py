import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ztb_fetcher.config import Config


class ConfigTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
