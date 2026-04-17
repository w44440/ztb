"""配置文件"""

import json
import os
from pathlib import Path

# 数据目录（固定在用户主目录，uv tool install 后路径不变）
DATA_DIR = Path.home() / ".ztb" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# DuckDB 数据库路径
DUCKDB_PATH = DATA_DIR / "zt_data.duckdb"

# 日志文件路径
LOG_FILE = DATA_DIR / "ztb.log"

# 同花顺配置
THS_QUERY_TEMPLATE = "{date_str}涨停，非ST"
THS_SUMMARY_IMAGE_URL_TEMPLATE = (
    "https://ozone.10jqka.com.cn/open/api/draw_lots/v1/rank/summary_image?date={date_str}"
)

# 韭研公社配置
JYGS_BASE_URL = "https://www.jiuyangongshe.com/action/"
JYGS_LOGIN_URL = "https://www.jiuyangongshe.com/"
JYGS_CACHE_DIR = DATA_DIR / "jygs_cache"
JYGS_CACHE_DIR.mkdir(exist_ok=True)
THS_KIMI_CACHE_DIR = DATA_DIR / "ths_kimi_cache"
THS_KIMI_CACHE_DIR.mkdir(exist_ok=True)
JYGS_USER_DATA_DIR = DATA_DIR / "playwright" / "jygs"
JYGS_USER_DATA_DIR.parent.mkdir(parents=True, exist_ok=True)

# 分析报告
REPORTS_DIR = DATA_DIR / "reports"
ANALYSIS_DAYS = 5  # 默认分析窗口天数

# AI agent 读取以判断运行结果
STATUS_FILE = DATA_DIR / "last_run.json"


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
