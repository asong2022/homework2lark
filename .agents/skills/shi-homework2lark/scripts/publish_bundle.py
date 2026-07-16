from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from doctor import BundleContractError, load_bundle
from package_bundle import PackageError, collect_files


class PublishError(ValueError):
    """Raised when a Skill mirror cannot be updated safely."""


def _hash_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(root: Path, files: list[Path]) -> dict[str, str]:
    return {relative.as_posix(): _hash_bytes(root / relative) for relative in files}


def _assert_direct_child(path: Path, root: Path, prefix: str) -> None:
    if path.parent != root or not path.name.startswith(prefix):
        raise PublishError("refusing filesystem operation outside the validated target root")


def validate_family_root(repo: Path) -> Path:
    repo = repo.resolve()
    target_root = repo / "skills"
    if not (repo / "README.md").is_file():
        raise PublishError("family repository README.md is missing")
    if not (repo / "scripts" / "sync-to-local.ps1").is_file():
        raise PublishError("family repository sync script is missing")
    if not target_root.is_dir():
        raise PublishError("family repository skills directory is missing")
    return target_root


def default_global_roots() -> list[tuple[str, Path]]:
    home = Path.home()
    candidates = [
        ("agents", home / ".agents" / "skills"),
        ("claude", home / ".claude" / "skills"),
        ("codex", home / ".codex" / "skills"),
    ]
    return [(kind, path.resolve()) for kind, path in candidates if path.is_dir()]


def sync_to_root(
    source: Path,
    target_root: Path,
    *,
    kind: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    source = source.resolve()
    target_root = target_root.resolve()
    if not target_root.is_dir():
        raise PublishError("target Skill root is missing")
    manifest = load_bundle(source)
    files = collect_files(source, manifest)
    source_hashes = tree_hashes(source, files)
    destination = target_root / manifest["name"]
    if destination.parent != target_root or destination.name != "shi-homework2lark":
        raise PublishError("destination is outside the validated Skill root")

    if dry_run:
        return {
            "kind": kind,
            "status": "would_sync",
            "fileCount": len(files),
            "hashesVerified": False,
        }

    suffix = uuid.uuid4().hex
    staging = target_root / f".shi-homework2lark.staging-{suffix}"
    backup = target_root / f".shi-homework2lark.backup-{suffix}"
    _assert_direct_child(staging, target_root, ".shi-homework2lark.staging-")
    _assert_direct_child(backup, target_root, ".shi-homework2lark.backup-")
    old_moved = False
    new_moved = False
    try:
        staging.mkdir()
        for relative in files:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, target)
        if tree_hashes(staging, files) != source_hashes:
            raise PublishError("staging hash verification failed")

        if destination.exists():
            destination.replace(backup)
            old_moved = True
        staging.replace(destination)
        new_moved = True
        if tree_hashes(destination, files) != source_hashes:
            raise PublishError("published mirror hash verification failed")
        if backup.exists():
            _assert_direct_child(backup, target_root, ".shi-homework2lark.backup-")
            shutil.rmtree(backup)
            old_moved = False
    except Exception:
        if destination.exists() and new_moved:
            shutil.rmtree(destination)
        if backup.exists() and old_moved:
            backup.replace(destination)
            old_moved = False
        raise
    finally:
        if staging.exists():
            _assert_direct_child(staging, target_root, ".shi-homework2lark.staging-")
            shutil.rmtree(staging)
        if backup.exists() and not old_moved:
            _assert_direct_child(backup, target_root, ".shi-homework2lark.backup-")
            shutil.rmtree(backup)

    return {
        "kind": kind,
        "status": "synced",
        "fileCount": len(files),
        "hashesVerified": True,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mirror shi-homework2lark to the 阿松 family repo and local Skill roots."
    )
    parser.add_argument("--family-repo", type=Path)
    parser.add_argument("--global-roots", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.family_repo is None and not args.global_roots:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "target_required",
                    "message": "choose --family-repo and/or --global-roots",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    source = Path(__file__).resolve().parent.parent
    targets: list[tuple[str, Path]] = []
    try:
        if args.family_repo is not None:
            targets.append(("family", validate_family_root(args.family_repo)))
        if args.global_roots:
            targets.extend(default_global_roots())
        if not targets:
            raise PublishError("no existing target Skill root was found")

        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for kind, root in targets:
            key = os.path.normcase(str(root))
            if key in seen:
                continue
            seen.add(key)
            results.append(sync_to_root(source, root, kind=kind, dry_run=args.dry_run))
    except (BundleContractError, PackageError, PublishError, OSError) as exc:
        print(
            json.dumps(
                {"ok": False, "error": "publish_failed", "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "bundle": "shi-homework2lark",
                "dryRun": args.dry_run,
                "targets": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
