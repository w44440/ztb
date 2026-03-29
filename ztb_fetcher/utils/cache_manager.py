"""缓存管理模块"""
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class CacheManager:
    """文件缓存管理器"""

    def __init__(self, cache_dir: Path, use_monthly_subfolder: bool = False):
        self.cache_dir = cache_dir
        self.use_monthly_subfolder = use_monthly_subfolder
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, key: str, suffix: str = ".txt") -> Path:
        """获取缓存文件路径"""
        if self.use_monthly_subfolder and len(key) >= 7:
            # 假设 key 是日期格式 YYYY-MM-DD
            month_folder = key[:7]  # YYYY-MM
            folder = self.cache_dir / month_folder
            folder.mkdir(exist_ok=True)
            return folder / f"{key}{suffix}"
        return self.cache_dir / f"{key}{suffix}"

    def get(self, key: str, suffix: str = ".txt") -> str | None:
        """获取缓存内容"""
        cache_path = self._get_cache_path(key, suffix)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"读取缓存失败 {cache_path}: {e}")
            return None

    def set(self, key: str, content: str, suffix: str = ".txt") -> bool:
        """设置缓存内容"""
        cache_path = self._get_cache_path(key, suffix)

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception as e:
            logger.warning(f"写入缓存失败 {cache_path}: {e}")
            return False

    def exists(self, key: str, suffix: str = ".txt") -> bool:
        """检查缓存是否存在"""
        cache_path = self._get_cache_path(key, suffix)
        return cache_path.exists()

    def clear(self, days: int = 30):
        """清理过期缓存"""
        cutoff = datetime.now() - timedelta(days=days)

        for path in self.cache_dir.rglob("*"):
            if path.is_file():
                try:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime)
                    if mtime < cutoff:
                        path.unlink()
                        logger.debug(f"删除过期缓存: {path}")
                except Exception as e:
                    logger.warning(f"清理缓存失败 {path}: {e}")
