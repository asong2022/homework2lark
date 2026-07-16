from __future__ import annotations

from pathlib import Path

import pytest

from mistake_notebook_api.domain.errors import AppError
from mistake_notebook_api.infrastructure.storage.local import LocalFileStorageAdapter


def test_local_storage_is_immutable_and_path_safe(tmp_path: Path) -> None:
    storage = LocalFileStorageAdapter(tmp_path)
    storage.write("sources/asset_1.png", b"original")
    assert storage.read("sources/asset_1.png") == b"original"
    assert storage.exists("sources/asset_1.png")

    with pytest.raises(AppError):
        storage.write("sources/asset_1.png", b"overwritten")
    with pytest.raises(AppError):
        storage.read("../secret")
    with pytest.raises(AppError):
        storage.read("..\\secret")

    storage.delete("sources/asset_1.png")
    assert not storage.exists("sources/asset_1.png")
