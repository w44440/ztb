"""配置文件"""
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 数据目录
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

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
