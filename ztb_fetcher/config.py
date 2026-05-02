"""配置文件"""

import json
import os
from pathlib import Path


class Config:
    """配置管理类

    优先级：环境变量 > 配置文件 > 默认值
    """

    CONFIG_DIR = Path.home() / ".ztb"
    CONFIG_FILE = CONFIG_DIR / "config.json"

    def __init__(self):
        self._config = self._load_config()

    def _load_config(self) -> dict:
        """加载配置文件"""
        if self.CONFIG_FILE.exists():
            try:
                return json.loads(self.CONFIG_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def save(self) -> None:
        """保存配置到文件"""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.CONFIG_FILE.write_text(
            json.dumps(self._config, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get(self, key: str, default=None) -> str | None:
        """获取配置值

        优先级：环境变量 > 配置文件 > 默认值
        """
        # 首先检查环境变量（支持 ZTB_ 前缀的大写形式）
        env_key = f"ZTB_{key.upper()}"
        env_value = os.getenv(env_key)
        if env_value:
            return env_value

        return self._config.get(key, default)

    def set(self, key: str, value: str) -> None:
        """设置配置值并保存"""
        self._config[key] = value
        self.save()


# 全局配置实例
_config = Config()


def get_config(key: str, default=None) -> str | None:
    """获取配置值的便捷函数"""
    return _config.get(key, default)


def _resolve_path_config(key: str, default: str | Path) -> Path:
    configured = get_config(key, str(default))
    return Path(str(configured)).expanduser()


# 主数据目录默认放在 HDD；可用 ZTB_DATA_ROOT 或 ~/.ztb/config.json 的 data_root 覆盖。
DATA_ROOT = _resolve_path_config("data_root", "/data/ops-data/ztb")
DATA_ROOT.mkdir(parents=True, exist_ok=True)

# 兼容既有命名：DATA_DIR 代表主数据目录。
DATA_DIR = DATA_ROOT

# DuckDB 数据库路径
DUCKDB_PATH = DATA_ROOT / "zt_data.duckdb"

# 日志文件路径
LOG_DIR = DATA_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "ztb.log"

# 同花顺配置
THS_QUERY_TEMPLATE = "{date_str}涨停，非ST"
THS_SUMMARY_IMAGE_URL_TEMPLATE = (
    "https://ozone.10jqka.com.cn/open/api/draw_lots/v1/rank/summary_image?date={date_str}"
)

# 韭研公社配置
JYGS_BASE_URL = "https://www.jiuyangongshe.com/action/"
JYGS_LOGIN_URL = "https://www.jiuyangongshe.com/"
JYGS_CACHE_DIR = DATA_ROOT / "jygs_cache"
JYGS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
THS_OCR_CACHE_DIR = DATA_ROOT / "ths_ocr_cache"
THS_OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 分析报告
REPORTS_DIR = DATA_ROOT / "reports"
ANALYSIS_DAYS = 5  # 默认分析窗口天数

# AI agent 读取以判断运行结果
STATUS_FILE = DATA_ROOT / "last_run.json"
