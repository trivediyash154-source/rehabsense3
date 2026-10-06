"""Object storage for large files: research exports, raw archives, model bundles.

PostgreSQL holds the metadata (`recording_artifacts`: storage URI, SHA-256,
size, schema version); the bytes live here.

    STORAGE_BACKEND=local   a directory (development; in production only on a
                            persistent volume, set STORAGE_LOCAL_DIR explicitly)
    STORAGE_BACKEND=s3      any S3-compatible service (AWS S3, Cloudflare R2,
                            MinIO, ...) via boto3; credentials from the
                            standard AWS_* environment variables, never from code

Nothing here writes to /tmp or relies on process memory for durability.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings


@dataclass
class StoredObject:
    uri: str
    sha256: str
    size_bytes: int


def _hash(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


class LocalStorage:
    scheme = "local"

    def __init__(self, base: str):
        self.base = Path(base).resolve()

    def _path(self, key: str) -> Path:
        p = (self.base / key).resolve()
        if self.base not in p.parents and p != self.base:
            raise ValueError("storage key escapes the storage root")
        return p

    def put_file(self, key: str, src: Path) -> StoredObject:
        sha, size = _hash(src)
        dst = self._path(key)
        if dst.exists():
            raise FileExistsError(f"refusing to overwrite stored object {key}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return StoredObject(f"local://{key}", sha, size)

    def get_file(self, key: str, dst: Path) -> None:
        shutil.copyfile(self._path(key), dst)

    def health(self) -> bool:
        try:
            self.base.mkdir(parents=True, exist_ok=True)
            probe = self.base / ".health"
            probe.write_bytes(b"ok")
            probe.unlink()
            return True
        except OSError:
            return False


class S3Storage:
    scheme = "s3"

    def __init__(self, bucket: str, prefix: str, endpoint_url: str | None, region: str | None):
        import boto3  # optional dependency; only needed when STORAGE_BACKEND=s3

        self.bucket, self.prefix = bucket, prefix
        self.client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)

    def put_file(self, key: str, src: Path) -> StoredObject:
        sha, size = _hash(src)
        full = self.prefix + key
        try:
            self.client.head_object(Bucket=self.bucket, Key=full)
            raise FileExistsError(f"refusing to overwrite stored object {key}")
        except self.client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise
        self.client.upload_file(str(src), self.bucket, full,
                                ExtraArgs={"Metadata": {"sha256": sha}})
        return StoredObject(f"s3://{self.bucket}/{full}", sha, size)

    def get_file(self, key: str, dst: Path) -> None:
        self.client.download_file(self.bucket, self.prefix + key, str(dst))

    def health(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


def get_storage():
    s = get_settings()
    if s.storage_backend == "s3":
        if not s.storage_s3_bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 requires STORAGE_S3_BUCKET")
        return S3Storage(s.storage_s3_bucket, s.storage_s3_prefix, s.storage_s3_endpoint_url,
                         s.storage_s3_region)
    if s.storage_backend == "local":
        base = Path(s.storage_local_dir)
        if not base.is_absolute():
            base = Path(__file__).resolve().parents[2] / base
        return LocalStorage(str(base))
    raise RuntimeError(f"unknown STORAGE_BACKEND {s.storage_backend!r}")
