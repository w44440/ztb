"""S3-compatible client for website state files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class StateStoreError(RuntimeError):
    """Raised when state storage operations fail."""


class StateStoreConfigError(StateStoreError):
    """Raised when required state storage config is missing."""


@dataclass(frozen=True)
class S3Config:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    object_key: str
    region: str = "auto"

    @classmethod
    def from_env(cls, object_key_default: str) -> "S3Config":
        endpoint = _required_env("ZTB_STATE_S3_ENDPOINT")
        access_key = _required_env("ZTB_STATE_S3_ACCESS_KEY")
        secret_key = _required_env("ZTB_STATE_S3_SECRET_KEY")
        bucket = _required_env("ZTB_STATE_S3_BUCKET")
        return cls(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            bucket=bucket,
            object_key=object_key_default,
        )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise StateStoreConfigError(f"缺少环境变量: {name}")
    return value


class S3StateClient:
    """S3 client backed by boto3, compatible with Cloudflare R2 and RustFS."""

    def __init__(self, config: S3Config):
        self.config = config
        endpoint = config.endpoint
        if not endpoint.startswith(("http://", "https://")):
            endpoint = f"https://{endpoint}"
        self._client = boto3.client(
            service_name="s3",
            endpoint_url=endpoint,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name=config.region,
        )

    def download_file(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            self._client.download_file(self.config.bucket, self.config.object_key, str(tmp))
            tmp.replace(path)
        except (BotoCoreError, ClientError) as exc:
            tmp.unlink(missing_ok=True)
            raise StateStoreError(f"S3 下载失败: {exc}") from exc
        return path

    def upload_file(self, path: Path) -> None:
        if not path.exists():
            raise StateStoreError(f"状态文件不存在: {path}")
        try:
            self._client.upload_file(str(path), self.config.bucket, self.config.object_key)
        except (BotoCoreError, ClientError) as exc:
            raise StateStoreError(f"S3 上传失败: {exc}") from exc
