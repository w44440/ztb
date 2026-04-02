"""配置文件"""
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

# 韭研公社配置
JYGS_BASE_URL = "https://www.jiuyangongshe.com/action/"
JYGS_CACHE_DIR = DATA_DIR / "jygs_cache"
JYGS_CACHE_DIR.mkdir(exist_ok=True)

# 分析报告
REPORTS_DIR = DATA_DIR / "reports"
ANALYSIS_DAYS = 5  # 默认分析窗口天数

# AI agent 读取以判断运行结果
STATUS_FILE = DATA_DIR / "last_run.json"
