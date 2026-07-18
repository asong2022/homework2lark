from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from doctor import BundleContractError, load_bundle

TEXT_SUFFIXES = {".json", ".md", ".ps1", ".py", ".txt", ".yaml", ".yml"}
PRIVATE_PATH_PATTERNS = (
    re.compile(r"(?i)C:[\\/]+Users[\\/]+Administrator(?:[\\/]|\b)"),
    re.compile(r"(?i)E:[\\/]+Documents[\\/]+code[\\/]+作业试卷错题本(?:[\\/]|\b)"),
)
SECRET_PATTERNS = (
    re.compile(r"\b(?:BACK|AI)_[A-Z0-9]{12,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|app[_-]?secret)\s*[:=]\s*[\"']?"
        r"(?!<|\$\{|env\b|example\b|xxx\b)[A-Za-z0-9_-]{16,}"
    ),
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class PackageError(ValueError):
    """Raised when a Skill bundle cannot be safely packaged."""


def _is_excluded(relative: Path, manifest: dict[str, Any]) -> bool:
    resources = manifest["resources"]
    if any(part in resources["excludeNames"] for part in relative.parts):
        return True
    return relative.suffix.lower() in set(resources["excludeSuffixes"])


def collect_files(skill_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    files = [
        path
        for path in skill_dir.rglob("*")
        if path.is_file() and not _is_excluded(path.relative_to(skill_dir), manifest)
    ]
    relative_files = sorted(
        (path.relative_to(skill_dir) for path in files),
        key=lambda item: item.as_posix(),
    )
    if not relative_files:
        raise PackageError("bundle contains no files")
    for required in manifest["resources"]["requiredFiles"]:
        if Path(required) not in relative_files:
            raise PackageError(f"required bundle file is missing: {required}")
    return relative_files


def scan_private_content(skill_dir: Path, files: list[Path]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative in files:
        if relative.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = (skill_dir / relative).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise PackageError(f"text resource is not UTF-8: {relative.as_posix()}") from exc
        for pattern in PRIVATE_PATH_PATTERNS:
            if pattern.search(text):
                findings.append({"file": relative.as_posix(), "reason": "private_absolute_path"})
                break
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append({"file": relative.as_posix(), "reason": "possible_credential"})
                break
    return findings


def _write_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(filename=name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_package(skill_dir: Path, output: Path, *, overwrite: bool = False) -> dict[str, Any]:
    skill_dir = skill_dir.resolve()
    output = output.resolve()
    try:
        output.relative_to(skill_dir)
    except ValueError:
        pass
    else:
        raise PackageError("package output must be outside the skill source directory")
    if output.exists() and not overwrite:
        raise PackageError("package output already exists")

    manifest = load_bundle(skill_dir)
    files = collect_files(skill_dir, manifest)
    findings = scan_private_content(skill_dir, files)
    if findings:
        reasons = ", ".join(f"{item['file']}:{item['reason']}" for item in findings)
        raise PackageError(f"private-content scan failed: {reasons}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        with zipfile.ZipFile(temporary, mode="w") as archive:
            for relative in files:
                archive_name = PurePosixPath(manifest["name"], relative.as_posix()).as_posix()
                _write_entry(archive, archive_name, (skill_dir / relative).read_bytes())
        verify_package(temporary, expected_manifest=manifest)
        if output.exists():
            output.unlink()
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()

    return {
        "bundle": manifest["name"],
        "version": manifest["version"],
        "file": output.name,
        "fileCount": len(files),
        "sizeBytes": output.stat().st_size,
        "sha256": sha256_file(output),
        "privateContentFindings": 0,
    }


def verify_package(
    package: Path, *, expected_manifest: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not package.is_file():
        raise PackageError("package file is missing")
    try:
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            if not names or len(names) != len(set(names)):
                raise PackageError("package entries are empty or duplicated")
            parsed = [PurePosixPath(name) for name in names]
            if any(path.is_absolute() or ".." in path.parts for path in parsed):
                raise PackageError("package contains an unsafe entry path")
            roots = {path.parts[0] for path in parsed if path.parts}
            if roots != {"shi-homework2lark"}:
                raise PackageError("package must contain one shi-homework2lark root")
            manifest_name = "shi-homework2lark/bundle.json"
            if manifest_name not in names:
                raise PackageError("package bundle.json is missing")
            archived_manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError("package is unreadable") from exc

    if archived_manifest.get("schemaVersion") != "shi-skill-bundle-v1":
        raise PackageError("package bundle schema is invalid")
    if expected_manifest is not None and archived_manifest != expected_manifest:
        raise PackageError("packaged bundle manifest differs from source")
    exclude_names = set(archived_manifest["resources"]["excludeNames"])
    exclude_suffixes = set(archived_manifest["resources"]["excludeSuffixes"])
    for path in parsed:
        if any(part in exclude_names for part in path.parts):
            raise PackageError("package contains an excluded directory or file")
        if path.suffix.lower() in exclude_suffixes:
            raise PackageError("package contains an excluded file suffix")
    for required in archived_manifest["resources"]["requiredFiles"]:
        if PurePosixPath("shi-homework2lark", required).as_posix() not in names:
            raise PackageError(f"package required file is missing: {required}")
    return {
        "bundle": archived_manifest["name"],
        "version": archived_manifest["version"],
        "file": package.name,
        "fileCount": len(names),
        "sha256": sha256_file(package),
        "valid": True,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or verify shi-homework2lark.skill")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--overwrite", action="store_true")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--package", required=True, type=Path)
    return parser.parse_args(argv)


def _force_utf8_stdio() -> None:
    """Windows 控制台/管道默认 GBK；AI 消费的中文 JSON 必须始终按 UTF-8 输出。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = parse_args(argv)
    skill_dir = Path(__file__).resolve().parent.parent
    try:
        if args.command == "build":
            result = build_package(skill_dir, args.output, overwrite=args.overwrite)
        else:
            result = verify_package(args.package.resolve())
    except (BundleContractError, PackageError) as exc:
        print(
            json.dumps(
                {"ok": False, "error": "package_failed", "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
