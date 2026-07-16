from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath

from mistake_notebook_api.domain.errors import AppError


class LocalFileStorageAdapter:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if "\\" in key:
            raise AppError("storage_unavailable", "文件存储键无效。")
        posix = PurePosixPath(key)
        invalid_part = any(part in {"", ".", ".."} for part in posix.parts)
        if posix.is_absolute() or not posix.parts or invalid_part:
            raise AppError("storage_unavailable", "文件存储键无效。")
        candidate = self._root.joinpath(*posix.parts).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            raise AppError("storage_unavailable", "文件存储键无效。") from None
        return candidate

    def write(self, key: str, data: bytes) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise AppError("storage_unavailable", "目标文件已存在，未覆盖原始数据。")

        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=destination.parent, prefix=".write-", delete=False
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, destination)
        except OSError:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
            raise AppError("storage_unavailable", "文件保存失败，请检查本地存储。", True) from None

    def read(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            raise AppError("storage_unavailable", "保存的文件不存在。") from None
        except OSError:
            raise AppError("storage_unavailable", "文件读取失败，请检查本地存储。", True) from None

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError:
            raise AppError("storage_unavailable", "文件删除失败，请检查本地存储。", True) from None

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()
