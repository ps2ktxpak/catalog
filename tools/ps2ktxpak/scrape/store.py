"""The scraper's bucket, through rclone: an R2 remote in the container, or a local directory in tests.

Layout:
  sources/<url id>/<file>     what the host served, byte for byte, once per download link
  packs/<key>.tar.zst         the converted archive, under the object name the catalog will use
  results/<key>.json          what happened to each pack (see job.Result)
  results/index-<shard>.json  every result in one file, for `ps2ktxpak scrape apply`
  withdrawn/packs/<object>    a hosted pack taken off the public bucket when withdrawn, kept as it was
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class Store:
    def __init__(self, remote: str):
        self.remote = remote.rstrip("/")

    def _path(self, key: str) -> str:
        return f"{self.remote}/{key}"

    def _rclone(self, *args, data: bytes | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["rclone", *args], input=data, capture_output=True,
                              stdin=None if data is not None else subprocess.DEVNULL)

    def put(self, local: Path, key: str) -> None:
        p = self._rclone("copyto", "--s3-chunk-size", "64M", str(local), self._path(key))
        if p.returncode:
            raise RuntimeError(f"upload of {key} failed: {p.stderr.decode()[-300:]}")

    def put_json(self, obj, key: str) -> None:
        p = self._rclone("rcat", self._path(key), data=json.dumps(obj, indent=1, sort_keys=True).encode())
        if p.returncode:
            raise RuntimeError(f"upload of {key} failed: {p.stderr.decode()[-300:]}")

    def get_json(self, key: str):
        p = self._rclone("cat", self._path(key))
        if p.returncode or not p.stdout:
            return None
        return json.loads(p.stdout)

    def list(self, prefix: str) -> list[str]:
        p = self._rclone("lsf", "-R", "--files-only", self._path(prefix))
        if p.returncode:
            return []
        return [f"{prefix.rstrip('/')}/{line}" for line in p.stdout.decode().splitlines() if line]

    def size(self, key: str) -> int | None:
        p = self._rclone("lsjson", self._path(key))
        if p.returncode:
            return None
        items = json.loads(p.stdout or b"[]")
        return items[0]["Size"] if items else None
