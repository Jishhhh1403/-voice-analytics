from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import Settings


@dataclass
class StoredObject:
    uri: str
    key: str
    generation: str
    size_bytes: int
    sha256: str
    uploaded_at: str
    content_type: str = "text/csv"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ObjectStore:
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        raise NotImplementedError

    def read_bytes(self, uri: str, generation: str | None = None) -> tuple[bytes, StoredObject]:
        raise NotImplementedError

    def stat(self, uri: str, generation: str | None = None) -> StoredObject:
        raise NotImplementedError

    def list_prefix(self, prefix: str) -> list[StoredObject]:
        raise NotImplementedError


class LocalObjectStore(ObjectStore):
    """Filesystem-backed immutable object store.

    Every write creates a content-addressed version under `.versions/` in addition
    to updating the current object pointer. The generation is the SHA-256 digest,
    so reruns against the same object are naturally idempotent.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".versions").mkdir(parents=True, exist_ok=True)
        (self.root / ".meta").mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        clean = key.lstrip("/").replace("\\", "/")
        path = (self.root / clean).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise ValueError("invalid object key")
        return path

    def _meta_path(self, key: str) -> Path:
        clean = key.lstrip("/").replace("\\", "/").replace("/", "__")
        return self.root / ".meta" / f"{clean}.json"

    def _key_from_uri(self, uri: str) -> str:
        if uri.startswith("local://"):
            return uri[len("local://") :].lstrip("/")
        if uri.startswith("file://"):
            path = Path(urlparse(uri).path)
            try:
                return str(path.resolve().relative_to(self.root.resolve())).replace("\\", "/")
            except ValueError:
                return str(path.resolve())
        return uri.lstrip("/")

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        key = key.lstrip("/").replace("\\", "/")
        digest = sha256_bytes(data)
        generation = digest[:24]
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically so a reader never sees a partial object.
        tmp = path.with_suffix(path.suffix + f".tmp-{generation}")
        tmp.write_bytes(data)
        tmp.replace(path)
        version_dir = self.root / ".versions" / key
        version_dir.mkdir(parents=True, exist_ok=True)
        version_path = version_dir / generation
        if not version_path.exists():
            version_path.write_bytes(data)
        meta = StoredObject(
            uri=f"local://{key}",
            key=key,
            generation=generation,
            size_bytes=len(data),
            sha256=digest,
            uploaded_at=now_iso(),
            content_type=content_type or mimetypes.guess_type(key)[0] or "application/octet-stream",
        )
        self._meta_path(key).write_text(json.dumps(meta.to_dict(), indent=2), encoding="utf-8")
        return meta

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> StoredObject:
        return self.put_bytes(key, Path(path).read_bytes(), content_type)

    def _meta(self, key: str) -> dict[str, Any]:
        meta_path = self._meta_path(key)
        if not meta_path.exists():
            raise FileNotFoundError(f"object not found: {key}")
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def stat(self, uri: str, generation: str | None = None) -> StoredObject:
        key = self._key_from_uri(uri)
        meta = self._meta(key)
        if generation and generation != meta.get("generation"):
            version_path = self.root / ".versions" / key / generation
            if not version_path.exists():
                raise FileNotFoundError(f"object generation not found: {key}@{generation}")
            data = version_path.read_bytes()
            meta = dict(meta)
            meta["generation"] = generation
            meta["sha256"] = hashlib.sha256(data).hexdigest()
            meta["size_bytes"] = len(data)
        return StoredObject(**meta)

    def read_bytes(self, uri: str, generation: str | None = None) -> tuple[bytes, StoredObject]:
        key = self._key_from_uri(uri)
        meta = self.stat(uri, generation)
        if generation:
            path = self.root / ".versions" / key / generation
        else:
            path = self._path(key)
        data = path.read_bytes()
        meta.sha256 = sha256_bytes(data)
        meta.size_bytes = len(data)
        meta.uri = f"local://{key}"
        return data, meta

    def list_prefix(self, prefix: str) -> list[StoredObject]:
        results: list[StoredObject] = []
        root = self._path(prefix)
        if root.is_file():
            return [self.stat(f"local://{prefix}")]
        if not root.exists():
            return results
        for path in root.rglob("*"):
            if path.is_file() and ".versions" not in path.parts and ".meta" not in path.parts:
                key = str(path.relative_to(self.root)).replace("\\", "/")
                try:
                    results.append(self.stat(f"local://{key}"))
                except FileNotFoundError:
                    continue
        return sorted(results, key=lambda item: item.uploaded_at, reverse=True)

    def ensure_sample_source(self, sample_path: Path, prefix: str = "feedback/source") -> StoredObject:
        key = f"{prefix}/{sample_path.name}"
        meta_path = self._meta_path(key)
        if meta_path.exists():
            return self.stat(f"local://{key}")
        return self.put_file(key, sample_path, "text/csv")


class GCSObjectStore(ObjectStore):
    """Thin adapter over google-cloud-storage, imported lazily."""

    def __init__(self, bucket_name: str) -> None:
        from google.cloud import storage  # type: ignore

        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)
        self.bucket_name = bucket_name

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        blob = self.bucket.blob(key)
        blob.content_type = content_type or "application/octet-stream"
        blob.upload_from_string(data, content_type=blob.content_type)
        blob.reload()
        return StoredObject(
            uri=f"gs://{self.bucket_name}/{key}",
            key=key,
            generation=str(blob.generation),
            size_bytes=blob.size or len(data),
            sha256=sha256_bytes(data),
            uploaded_at=blob.time_created.isoformat() if blob.time_created else now_iso(),
            content_type=blob.content_type or "application/octet-stream",
        )

    def _split(self, uri: str) -> tuple[str, str]:
        if not uri.startswith("gs://"):
            raise ValueError("expected gs:// URI")
        rest = uri[5:]
        bucket, _, key = rest.partition("/")
        if bucket != self.bucket_name:
            raise ValueError("object URI bucket does not match configured bucket")
        return bucket, key

    def stat(self, uri: str, generation: str | None = None) -> StoredObject:
        _, key = self._split(uri)
        blob = self.bucket.blob(key, generation=generation) if generation else self.bucket.blob(key)
        blob.reload()
        data = blob.download_as_bytes() if not generation else None
        digest = sha256_bytes(data) if data is not None else ""
        return StoredObject(
            uri=uri,
            key=key,
            generation=str(blob.generation),
            size_bytes=blob.size or 0,
            sha256=digest,
            uploaded_at=blob.time_created.isoformat() if blob.time_created else now_iso(),
            content_type=blob.content_type or "text/csv",
        )

    def read_bytes(self, uri: str, generation: str | None = None) -> tuple[bytes, StoredObject]:
        _, key = self._split(uri)
        blob = self.bucket.blob(key, generation=generation) if generation else self.bucket.blob(key)
        data = blob.download_as_bytes()
        meta = StoredObject(
            uri=uri,
            key=key,
            generation=str(blob.generation),
            size_bytes=len(data),
            sha256=sha256_bytes(data),
            uploaded_at=blob.time_created.isoformat() if blob.time_created else now_iso(),
            content_type=blob.content_type or "text/csv",
        )
        return data, meta

    def list_prefix(self, prefix: str) -> list[StoredObject]:
        blobs = self.client.list_blobs(self.bucket, prefix=prefix)
        return [
            StoredObject(
                uri=f"gs://{self.bucket_name}/{blob.name}",
                key=blob.name,
                generation=str(blob.generation),
                size_bytes=blob.size or 0,
                sha256="",
                uploaded_at=blob.time_created.isoformat() if blob.time_created else now_iso(),
                content_type=blob.content_type or "text/csv",
            )
            for blob in blobs
        ]


def build_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store.lower() == "gcs":
        if not settings.gcs_bucket:
            raise RuntimeError("OBJECT_STORE=gcs requires GCS_BUCKET")
        return GCSObjectStore(settings.gcs_bucket)
    return LocalObjectStore(settings.object_root)
