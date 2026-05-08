"""CLI for inspecting and managing local ChromaDB collections.

The CLI is intentionally limited to local collection administration:
listing collections, reporting integrity status, creating empty collections,
deleting collections, and creating timestamped backups. It avoids the
higher-level retriever helpers that resolve embedding models so common
operations stay fast and offline-safe.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

# Support direct execution via `uv run tools/collections_cli.py`, where Python
# otherwise sets sys.path to `tools/` instead of the repository root.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chromadb

_DEFAULT_PERSIST_DIR = "./knowledge_db"
_REPO_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _lazy_deps() -> dict[str, Any]:
    from hybrid_rag.config import DEFAULT_CONFIG
    from hybrid_rag.constants import COLLECTION_NAME_INVALID_MSG, KNOWLEDGE_DB_DIRECTORY
    from hybrid_rag.persistence import (
        load_config_from_disk,
        resolve_startup_config,
        save_config_to_disk,
    )
    from hybrid_rag.vectordb import is_valid_collection_name, list_existing_collections

    return {
        "DEFAULT_CONFIG": DEFAULT_CONFIG,
        "COLLECTION_NAME_INVALID_MSG": COLLECTION_NAME_INVALID_MSG,
        "KNOWLEDGE_DB_DIRECTORY": KNOWLEDGE_DB_DIRECTORY,
        "load_config_from_disk": load_config_from_disk,
        "resolve_startup_config": resolve_startup_config,
        "save_config_to_disk": save_config_to_disk,
        "is_valid_collection_name": is_valid_collection_name,
        "list_existing_collections": list_existing_collections,
    }

REQUIRED_VECTOR_FILES = {
    "data_level0.bin",
    "header.bin",
    "length.bin",
    "link_lists.bin",
}


def _sqlite_path(persist_dir: str) -> Path:
    return Path(persist_dir) / "chroma.sqlite3"


def _has_database(persist_dir: str) -> bool:
    return _sqlite_path(persist_dir).exists()


def _get_client(persist_dir: str) -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=persist_dir)


def _validate_collection_name(name: str) -> None:
    deps = _lazy_deps()
    if not deps["is_valid_collection_name"](name):
        raise ValueError(
            f"Invalid collection name '{name}': {deps['COLLECTION_NAME_INVALID_MSG']}"
        )


def _sqlite_connect_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    row = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _is_uuid_like(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def _resolve_active_collection_name(persist_dir: str) -> str | None:
    deps = _lazy_deps()
    resolve_startup_config = deps["resolve_startup_config"]
    load_config_from_disk = deps["load_config_from_disk"]
    try:
        return resolve_startup_config(persist_dir).collection_name
    except Exception:
        config = load_config_from_disk(persist_dir)
        if config is not None:
            return config.collection_name
        return None


def _default_backup_dir(persist_dir: str) -> Path:
    return Path(persist_dir).resolve().parent / "backup"


def _build_backup_path(persist_dir: str, backup_dir: str | None = None) -> Path:
    timestamp = datetime.now().strftime("%m_%d_%y_%H_%M_%S")
    target_dir = Path(backup_dir) if backup_dir is not None else _default_backup_dir(
        persist_dir
    )
    return target_dir / f"db_{timestamp}.bak"


def _build_model_backup_path(
    persist_dir: str,
    prefix: str,
    backup_dir: str | None = None,
) -> Path:
    timestamp = datetime.now().strftime("%m_%d_%y_%H_%M_%S")
    target_dir = Path(backup_dir) if backup_dir is not None else _default_backup_dir(
        persist_dir
    )
    return target_dir / f"{prefix}_{timestamp}.bak"


def _upsert_env_file(env_path: Path, values: dict[str, str]) -> None:
    existing_lines = env_path.read_text().splitlines() if env_path.exists() else []
    key_order = ["MCP_HOST", "MCP_TRANSPORT", "MCP_PORT", "COLLECTION_NAME"]
    pending = {key for key in key_order if key in values}
    updated_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated_lines.append(line)
            continue

        key, _, _ = line.partition("=")
        normalized_key = key.strip()
        if normalized_key in pending:
            updated_lines.append(f"{normalized_key}={values[normalized_key]}")
            pending.remove(normalized_key)
            continue

        updated_lines.append(line)

    if pending and updated_lines and updated_lines[-1].strip():
        updated_lines.append("")

    for key in key_order:
        if key in pending:
            updated_lines.append(f"{key}={values[key]}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(updated_lines) + "\n")


def _create_backup_archive(source_dir: str | Path, output_path: Path) -> Path:
    resolved_source_dir = Path(source_dir).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(
        output_path, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in sorted(resolved_source_dir.rglob("*")):
            if not path.is_file():
                continue
            archive.write(path, arcname=path.relative_to(resolved_source_dir))

    return output_path


def _create_backup_archive_from_sources(
    source_dirs: list[tuple[Path, Path]],
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(
        output_path, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for source_dir, archive_root in source_dirs:
            resolved_source_dir = source_dir.resolve()
            for path in sorted(resolved_source_dir.rglob("*")):
                if not path.is_file():
                    continue
                archive.write(
                    path,
                    arcname=archive_root / path.relative_to(resolved_source_dir),
                )

    return output_path


def _resolve_model_directory(model_type: str, persist_dir: str) -> tuple[Path, str]:
    deps = _lazy_deps()
    config = deps["load_config_from_disk"](persist_dir) or deps["DEFAULT_CONFIG"]

    if model_type == "st":
        model_path = Path(config.embedding_model_path)
        label = "sentence transformer"
    else:
        model_path = Path(config.reranker_model_path)
        label = "cross encoder"

    if not model_path.is_absolute():
        model_path = (_REPO_ROOT / model_path).resolve()

    return model_path, label


def _resolve_sentence_transformer_paths(persist_dir: str) -> list[tuple[Path, Path]]:
    model_path, _ = _resolve_model_directory("st", persist_dir)
    return [
        (model_path.resolve(), Path("models") / "embedding"),
        ((model_path.parent / "custom_embed").resolve(), Path("models") / "custom_embed"),
    ]



def _resolve_sentence_transformer_backup_sources(
    persist_dir: str,
) -> list[tuple[Path, Path]]:
    source_dirs: list[tuple[Path, Path]] = []
    seen_paths: set[Path] = set()

    for source_dir, archive_root in _resolve_sentence_transformer_paths(persist_dir):
        resolved_source_dir = source_dir.resolve()
        if resolved_source_dir in seen_paths or not resolved_source_dir.is_dir():
            continue
        source_dirs.append((resolved_source_dir, archive_root))
        seen_paths.add(resolved_source_dir)

    return source_dirs


def _parse_backup_timestamp(file_path: Path, prefix: str) -> datetime | None:
    pattern = re.compile(
        rf"^{re.escape(prefix)}_(\d{{2}}_\d{{2}}_\d{{2}}_\d{{2}}_\d{{2}}_\d{{2}})\.bak$"
    )
    match = pattern.match(file_path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%m_%d_%y_%H_%M_%S")
    except ValueError:
        return None



def _format_backup_timestamp(file_path: Path) -> str:
    prefix = file_path.name.split("_", 1)[0]
    parsed = _parse_backup_timestamp(file_path, prefix)
    if parsed is None:
        return "unknown"
    return parsed.strftime("%Y-%m-%d %H:%M:%S")



def _confirm_destructive_restore(
    force: bool,
    label: str,
    backup_archive: Path,
    target_paths: list[Path],
) -> bool:
    if force:
        return True

    targets = "\n".join(f"  - {path}" for path in target_paths)
    prompt = (
        f"Restore will replace the existing {label} data.\n"
        f"Source: {backup_archive}\n"
        f"Target:\n{targets}\n"
        f"Backup timestamp: {_format_backup_timestamp(backup_archive)}\n"
        "This cannot be undone. Continue? [y/N]: "
    )
    return input(prompt).strip().lower() in {"y", "yes"}


def _find_latest_backup_by_prefix(
    persist_dir: str,
    prefix: str,
    backup_dir: str | None = None,
) -> Path | None:
    target_dir = Path(backup_dir) if backup_dir is not None else _default_backup_dir(
        persist_dir
    )
    if not target_dir.exists():
        return None

    candidates: list[tuple[datetime, Path]] = []
    for file_path in target_dir.glob(f"{prefix}_*.bak"):
        if not file_path.is_file():
            continue
        parsed = _parse_backup_timestamp(file_path, prefix)
        if parsed is not None:
            candidates.append((parsed, file_path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _sanitize_archive_members(archive: zipfile.ZipFile) -> None:
    for member in archive.infolist():
        path = Path(member.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe archive path: {member.filename}")

        mode = (member.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError(f"Archive contains symbolic link: {member.filename}")


def _extract_archive_to_directory(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path, mode="r") as archive:
        _sanitize_archive_members(archive)
        archive.extractall(destination)


def _restore_backup_to_target_dir(
    target_dir: Path,
    backup_archive: Path,
    *,
    force: bool,
    label: str,
    required_path: str | None = None,
) -> None:
    resolved_target_dir = target_dir.resolve()
    if not _confirm_destructive_restore(
        force=force,
        label=label,
        backup_archive=backup_archive,
        target_paths=[resolved_target_dir],
    ):
        raise RuntimeError("restore cancelled")

    with tempfile.TemporaryDirectory(prefix="restore.") as temp_dir:
        staging_dir = Path(temp_dir) / "staging"
        extract_dir = Path(temp_dir) / "extract"
        staging_dir.mkdir(parents=True, exist_ok=True)
        extract_dir.mkdir(parents=True, exist_ok=True)

        _extract_archive_to_directory(backup_archive, extract_dir)

        extracted_files = [path for path in extract_dir.rglob("*") if path.is_file()]
        if not extracted_files:
            raise ValueError("Backup archive is invalid: no files")

        if required_path is not None and not (extract_dir / required_path).exists():
            raise ValueError(f"Backup archive is invalid: missing {required_path}")

        shutil.move(str(extract_dir), str(staging_dir / "restore_payload"))
        _replace_directory_from_staging(
            staging_dir / "restore_payload",
            resolved_target_dir,
        )


def _replace_directory_from_staging(staged_dir: Path, target_dir: Path) -> None:
    resolved_target_dir = target_dir.resolve()
    if resolved_target_dir.exists():
        shutil.rmtree(resolved_target_dir)
    resolved_target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staged_dir), str(resolved_target_dir))


def _restore_sentence_transformer_backup(
    persist_dir: str,
    backup_archive: Path,
    *,
    force: bool,
) -> None:
    model_dir, label = _resolve_model_directory("st", persist_dir)
    target_dirs = _resolve_sentence_transformer_paths(persist_dir)

    if not _confirm_destructive_restore(
        force=force,
        label=label,
        backup_archive=backup_archive,
        target_paths=[target_dir for target_dir, _ in target_dirs],
    ):
        raise RuntimeError("restore cancelled")

    with tempfile.TemporaryDirectory(prefix="restore.") as temp_dir:
        extract_dir = Path(temp_dir) / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        _extract_archive_to_directory(backup_archive, extract_dir)

        extracted_files = [path for path in extract_dir.rglob("*") if path.is_file()]
        if not extracted_files:
            raise ValueError("Backup archive is invalid: no files")

        extracted_embedding_dir = extract_dir / "models" / "embedding"
        if extracted_embedding_dir.is_dir():
            for target_dir, archive_root in target_dirs:
                extracted_dir = extract_dir / archive_root
                if not extracted_dir.is_dir():
                    continue
                _replace_directory_from_staging(extracted_dir, target_dir)
            return

        _replace_directory_from_staging(extract_dir, model_dir)


def _get_collection_names(persist_dir: str) -> list[str]:
    if not _has_database(persist_dir):
        return []
    deps = _lazy_deps()
    return sorted(deps["list_existing_collections"](persist_dir))


def _get_collection_counts(persist_dir: str) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    if not _has_database(persist_dir):
        return counts

    client = _get_client(persist_dir)
    for name in _get_collection_names(persist_dir):
        try:
            counts[name] = client.get_collection(name).count()
        except Exception:
            counts[name] = None
    return counts


def _gather_status_rows(persist_dir: str) -> list[dict[str, Any]]:
    db_path = _sqlite_path(persist_dir)
    if not db_path.exists():
        return []

    counts = _get_collection_counts(persist_dir)
    vector_segment_ids_by_collection: dict[str, list[str]] = {}
    issues_by_collection: dict[str, list[str]] = {}

    with _sqlite_connect_readonly(db_path) as connection:
        cursor = connection.cursor()

        if cursor.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity check failed")

        if not _table_exists(cursor, "collections"):
            raise RuntimeError("Missing required SQLite table: collections")

        collection_rows = cursor.execute(
            "SELECT id, name FROM collections ORDER BY name"
        ).fetchall()

        collection_ids = {
            collection_id: name for collection_id, name in collection_rows
        }
        for name in collection_ids.values():
            issues_by_collection[name] = []
            vector_segment_ids_by_collection[name] = []

        if _table_exists(cursor, "segments"):
            segment_rows = cursor.execute(
                "SELECT id, type, scope, collection FROM segments"
            ).fetchall()
            for segment_id, segment_type, scope, collection_id in segment_rows:
                collection_name = collection_ids.get(collection_id)
                if collection_name is None:
                    continue
                if scope == "VECTOR" or "vector/hnsw-local-persisted" in segment_type:
                    vector_segment_ids_by_collection[collection_name].append(segment_id)
        else:
            for name in issues_by_collection:
                issues_by_collection[name].append("missing segments table")

    rows: list[dict[str, Any]] = []
    persist_path = Path(persist_dir)
    for collection_name in sorted(issues_by_collection):
        document_count = counts.get(collection_name)
        issues = issues_by_collection[collection_name]
        vector_ids = vector_segment_ids_by_collection.get(collection_name, [])

        for segment_id in vector_ids:
            if not _is_uuid_like(segment_id):
                issues.append(f"invalid vector segment id: {segment_id}")
                continue
            segment_dir = persist_path / segment_id
            if segment_dir.exists():
                if not segment_dir.is_dir():
                    issues.append(
                        f"vector segment path is not a directory: {segment_id}"
                    )
                    continue
                missing_files = REQUIRED_VECTOR_FILES - {
                    child.name for child in segment_dir.iterdir() if child.is_file()
                }
                if missing_files:
                    issues.append(
                        "vector segment directory missing files: "
                        f"{segment_id} -> {', '.join(sorted(missing_files))}"
                    )
                continue

            if (document_count or 0) > 0:
                issues.append(f"missing vector segment directory: {segment_id}")

        rows.append(
            {
                "name": collection_name,
                "documents": document_count,
                "corrupted": bool(issues) or document_count is None,
                "issues": issues,
            }
        )

    return rows


def _print_rows(rows: list[dict[str, Any]], as_json: bool, columns: list[str]) -> None:
    if as_json:
        print(json.dumps(rows, indent=2))
        return

    if not rows:
        print("No collections found.")
        return

    widths = {
        column: max(len(column), *(len(str(row.get(column, ""))) for row in rows))
        for column in columns
    }
    header = "  ".join(column.ljust(widths[column]) for column in columns)
    print(header)
    print("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        print(
            "  ".join(
                str(row.get(column, "")).ljust(widths[column]) for column in columns
            )
        )


def cmd_list(args: argparse.Namespace) -> int:
    rows = [
        {"name": name, "documents": count}
        for name, count in _get_collection_counts(args.persist_dir).items()
    ]
    _print_rows(rows, args.json, ["name", "documents"])
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        rows = _gather_status_rows(args.persist_dir)
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Failed to inspect collection status: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    if not rows:
        print("No collections found.")
        return 0

    table_rows = []
    for row in rows:
        table_rows.append(
            {
                "name": row["name"],
                "documents": row["documents"],
                "corrupted": row["corrupted"],
                "issues": "; ".join(row["issues"]),
            }
        )
    _print_rows(table_rows, False, ["name", "documents", "corrupted", "issues"])
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    try:
        _validate_collection_name(args.name)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    names = set(_get_collection_names(args.persist_dir))
    if args.name in names:
        print(f"Collection '{args.name}' already exists.")
        return 0

    client = _get_client(args.persist_dir)
    client.get_or_create_collection(
        name=args.name,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"Created empty collection '{args.name}'.")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    names = set(_get_collection_names(args.persist_dir))
    if args.name not in names:
        print(f"Collection '{args.name}' does not exist.", file=sys.stderr)
        return 1

    active_name = _resolve_active_collection_name(args.persist_dir)
    if args.name == active_name and not args.force_active:
        print(
            (
                f"Collection '{args.name}' is the active configured collection. "
                "Pass --force-active to delete it."
            ),
            file=sys.stderr,
        )
        return 1

    if not args.force:
        prompt = input(f"Delete collection '{args.name}'? [y/N]: ").strip().lower()
        if prompt not in {"y", "yes"}:
            print("Deletion cancelled.")
            return 0

    client = _get_client(args.persist_dir)
    client.delete_collection(args.name)
    print(f"Deleted collection '{args.name}'.")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    active_name = _resolve_active_collection_name(args.persist_dir)
    if active_name is None:
        print(
            "No active configured collection could be resolved for backup.",
            file=sys.stderr,
        )
        return 1

    names = set(_get_collection_names(args.persist_dir))
    if active_name not in names:
        print(
            (
                f"Active configured collection '{active_name}' does not exist in "
                f"'{args.persist_dir}'."
            ),
            file=sys.stderr,
        )
        return 1

    output_path = _build_backup_path(args.persist_dir, args.backup_dir)
    _create_backup_archive(args.persist_dir, output_path)
    print(f"Backed up active collection '{active_name}' to '{output_path}'.")
    return 0


def cmd_set_environment(args: argparse.Namespace) -> int:
    try:
        _validate_collection_name(args.collection_name)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    names = set(_get_collection_names(args.persist_dir))
    if args.collection_name not in names:
        print(
            f"Collection '{args.collection_name}' does not exist in '{args.persist_dir}'.",
            file=sys.stderr,
        )
        return 1

    values = {
        "MCP_HOST": "127.0.0.1",
        "MCP_TRANSPORT": "http",
        "MCP_PORT": "8001",
        "COLLECTION_NAME": args.collection_name,
    }

    env_path = Path(args.env_file).resolve()
    _upsert_env_file(env_path, values)
    for key, value in values.items():
        os.environ[key] = value

    deps = _lazy_deps()
    load_config_from_disk = deps["load_config_from_disk"]
    save_config_to_disk = deps["save_config_to_disk"]
    config = load_config_from_disk(args.persist_dir) or deps["DEFAULT_CONFIG"]
    updated_config = config.update(collection_name=args.collection_name)
    save_config_to_disk(updated_config, args.persist_dir)

    print(f"Updated environment file '{env_path}' for MCP server settings.")
    print(
        "Set MCP_HOST=127.0.0.1, MCP_TRANSPORT=http, MCP_PORT=8001, "
        f"COLLECTION_NAME={args.collection_name}."
    )
    print(
        f"Persisted default collection_name='{args.collection_name}' to config.json."
    )
    return 0


def cmd_model_backup(args: argparse.Namespace) -> int:
    model_dir, label = _resolve_model_directory(args.model_type, args.persist_dir)
    if args.model_type == "st":
        source_dirs = _resolve_sentence_transformer_backup_sources(args.persist_dir)
        if not source_dirs:
            print(
                "Configured sentence transformer model directories do not exist.",
                file=sys.stderr,
            )
            return 1
    else:
        if not model_dir.exists() or not model_dir.is_dir():
            print(
                f"Configured {label} model directory does not exist: '{model_dir}'.",
                file=sys.stderr,
            )
            return 1

    output_path = _build_model_backup_path(
        args.persist_dir,
        prefix=args.model_type,
        backup_dir=args.backup_dir,
    )
    if args.model_type == "st":
        _create_backup_archive_from_sources(source_dirs, output_path)
        backed_up_dirs = ", ".join(str(path) for path, _ in source_dirs)
        print(
            f"Backed up {label} model directories '{backed_up_dirs}' to '{output_path}'."
        )
    else:
        _create_backup_archive(model_dir, output_path)
        print(
            f"Backed up {label} model directory '{model_dir}' to '{output_path}'."
        )
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    latest_backup = _find_latest_backup_by_prefix(
        args.persist_dir,
        prefix="db",
        backup_dir=args.backup_dir,
    )
    if latest_backup is None:
        print("no DB backup found", file=sys.stderr)
        return 1

    try:
        _restore_backup_to_target_dir(
            Path(args.persist_dir),
            latest_backup,
            force=args.force,
            label="vector DB",
            required_path="chroma.sqlite3",
        )
    except RuntimeError as exc:
        if str(exc) == "restore cancelled":
            print("Restore cancelled.")
            return 0
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1

    print(f"Restored vector DB from '{latest_backup}'.")
    return 0


def cmd_model_restore(args: argparse.Namespace) -> int:
    latest_backup = _find_latest_backup_by_prefix(
        args.persist_dir,
        prefix=args.model_type,
        backup_dir=args.backup_dir,
    )

    if latest_backup is None:
        if args.model_type == "st":
            print("no sentence transformer backup found", file=sys.stderr)
        else:
            print("no cross encoder backup found", file=sys.stderr)
        return 1

    label = "sentence transformer" if args.model_type == "st" else "cross encoder"
    try:
        if args.model_type == "st":
            _restore_sentence_transformer_backup(
                args.persist_dir,
                latest_backup,
                force=args.force,
            )
        else:
            model_dir, label = _resolve_model_directory(args.model_type, args.persist_dir)
            _restore_backup_to_target_dir(
                model_dir,
                latest_backup,
                force=args.force,
                label=label,
            )
    except RuntimeError as exc:
        if str(exc) == "restore cancelled":
            print("Restore cancelled.")
            return 0
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1

    print(f"Restored {label} backup from '{latest_backup}'.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag-collections",
        description="Inspect and manage local ChromaDB collections.",
    )
    parser.add_argument(
        "--persist-dir",
        default=_DEFAULT_PERSIST_DIR,
        help="Path to the ChromaDB persistence directory.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List available collections.")
    list_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    list_parser.set_defaults(func=cmd_list)

    status_parser = subparsers.add_parser(
        "status", help="Report collection document counts and integrity status."
    )
    status_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    status_parser.set_defaults(func=cmd_status)

    add_parser = subparsers.add_parser("add", help="Create an empty collection.")
    add_parser.add_argument("name", help="Collection name to create.")
    add_parser.set_defaults(func=cmd_add)

    delete_parser = subparsers.add_parser("delete", help="Delete a collection.")
    delete_parser.add_argument("name", help="Collection name to delete.")
    delete_parser.add_argument(
        "--force", action="store_true", help="Skip interactive confirmation."
    )
    delete_parser.add_argument(
        "--force-active",
        action="store_true",
        help="Allow deleting the active configured collection.",
    )
    delete_parser.set_defaults(func=cmd_delete)

    backup_parser = subparsers.add_parser(
        "backup",
        help=(
            "Archive the current knowledge_db state for the active configured "
            "collection."
        ),
    )
    backup_parser.add_argument(
        "--backup-dir",
        help=(
            "Target directory for backup archives. Defaults to ./backup beside "
            "persist dir."
        ),
    )
    backup_parser.set_defaults(func=cmd_backup)

    set_env_parser = subparsers.add_parser(
        "set-environment",
        help="Set MCP server environment variables and default COLLECTION_NAME.",
    )
    set_env_parser.add_argument(
        "collection_name",
        help="Existing collection name to set as COLLECTION_NAME.",
    )
    set_env_parser.add_argument(
        "--env-file",
        default=".env",
        help="Environment file to update (default: ./.env).",
    )
    set_env_parser.set_defaults(func=cmd_set_environment)

    model_backup_parser = subparsers.add_parser(
        "model-backup",
        help=(
            "Archive the active collection with a model-family prefix in the "
            "backup filename."
        ),
    )
    model_backup_parser.add_argument(
        "model_type",
        choices=["st", "ce"],
        help="Model family prefix: 'st' (sentence-transformers) or 'ce' (cross-encoder).",
    )
    model_backup_parser.add_argument(
        "--backup-dir",
        help=(
            "Target directory for backup archives. Defaults to ./backup beside "
            "persist dir."
        ),
    )
    model_backup_parser.set_defaults(func=cmd_model_backup)

    restore_parser = subparsers.add_parser(
        "restore",
        help=(
            "Restore the latest db_<timestamp>.bak backup into the persistence "
            "directory."
        ),
    )
    restore_parser.add_argument(
        "--backup-dir",
        help=(
            "Directory that contains backup archives. Defaults to ./backup beside "
            "persist dir."
        ),
    )
    restore_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip destructive restore confirmation prompt.",
    )
    restore_parser.set_defaults(func=cmd_restore)

    model_restore_parser = subparsers.add_parser(
        "model-restore",
        help=(
            "Restore the latest model-family backup (st_<timestamp>.bak or "
            "ce_<timestamp>.bak) into the persistence directory."
        ),
    )
    model_restore_parser.add_argument(
        "model_type",
        choices=["st", "ce"],
        help="Model family prefix to restore: 'st' or 'ce'.",
    )
    model_restore_parser.add_argument(
        "--backup-dir",
        help=(
            "Directory that contains backup archives. Defaults to ./backup beside "
            "persist dir."
        ),
    )
    model_restore_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip destructive restore confirmation prompt.",
    )
    model_restore_parser.set_defaults(func=cmd_model_restore)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
