"""Tests for the ChromaDB collections CLI.

These tests keep the CLI contract stable without requiring model downloads.
All commands operate directly on a temporary Chroma persistence directory.
"""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import chromadb
import pytest

from tools.collections_cli import main

pytestmark = pytest.mark.cli


def _create_empty_collection(persist_dir: Path, name: str) -> None:
    client = chromadb.PersistentClient(path=str(persist_dir))
    client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})


def _create_populated_collection(persist_dir: Path, name: str) -> None:
    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_or_create_collection(
        name=name, metadata={"hnsw:space": "cosine"}
    )
    collection.add(
        ids=["1"],
        documents=["hello world"],
        embeddings=[[0.1, 0.2, 0.3]],
        metadatas=[{"source": "test"}],
    )


def _write_backup_archive(
    backup_dir: Path,
    filename: str,
    members: dict[str, bytes],
) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    archive_path = backup_dir / filename
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for relative_path, content in members.items():
            zf.writestr(relative_path, content)
    return archive_path


def test_list_shows_available_collections(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _create_empty_collection(tmp_path, "listme0")

    exit_code = main(["--persist-dir", str(tmp_path), "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "listme0" in captured.out
    assert "0" in captured.out


def test_add_creates_empty_collection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--persist-dir", str(tmp_path), "add", "create0"])

    captured = capsys.readouterr()
    client = chromadb.PersistentClient(path=str(tmp_path))
    assert exit_code == 0
    assert "Created empty collection 'create0'." in captured.out
    assert "create0" in [collection.name for collection in client.list_collections()]
    assert client.get_collection("create0").count() == 0


def test_add_rejects_invalid_collection_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--persist-dir", str(tmp_path), "add", "bad name"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Invalid collection name 'bad name'" in captured.err


def test_delete_removes_collection_with_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _create_empty_collection(tmp_path, "delete0")

    exit_code = main(["--persist-dir", str(tmp_path), "delete", "delete0", "--force"])

    captured = capsys.readouterr()
    client = chromadb.PersistentClient(path=str(tmp_path))
    assert exit_code == 0
    assert "Deleted collection 'delete0'." in captured.out
    assert "delete0" not in [collection.name for collection in client.list_collections()]


def test_delete_blocks_active_collection_without_force_active(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _create_empty_collection(tmp_path, "active0")
    (tmp_path / "config.json").write_text(
        """
{
  "semantic_top_k": 10,
  "keyword_top_k": 10,
  "final_top_k": 5,
  "semantic_weight": 0.65,
  "keyword_weight": 0.35,
  "enable_rerank": false,
  "pre_rerank_top_k": 20,
  "collection_name": "active0",
  "embedding_model_path": "./models/embedding",
  "reranker_model_path": "./models/reranker"
}
""".strip()
    )

    exit_code = main(["--persist-dir", str(tmp_path), "delete", "active0", "--force"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "is the active configured collection" in captured.err


def test_status_marks_healthy_collection_not_corrupted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _create_populated_collection(tmp_path, "status0")

    exit_code = main(["--persist-dir", str(tmp_path), "status", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"name": "status0"' in captured.out
    assert '"documents": 1' in captured.out
    assert '"corrupted": false' in captured.out


def test_status_marks_missing_vector_segment_directory_corrupted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _create_populated_collection(tmp_path, "broken0")
    db_path = tmp_path / "chroma.sqlite3"
    with sqlite3.connect(db_path) as connection:
        cursor = connection.cursor()
        vector_segment_id = cursor.execute(
            "SELECT id FROM segments WHERE scope = 'VECTOR' LIMIT 1"
        ).fetchone()[0]

    segment_dir = tmp_path / vector_segment_id
    for child in segment_dir.iterdir():
        child.unlink()
    segment_dir.rmdir()

    exit_code = main(["--persist-dir", str(tmp_path), "status", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"name": "broken0"' in captured.out
    assert '"corrupted": true' in captured.out
    assert "missing vector segment directory" in captured.out


def test_backup_creates_timestamped_archive_in_backup_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _create_empty_collection(tmp_path, "active0")
    (tmp_path / "config.json").write_text(
        """
{
  "semantic_top_k": 10,
  "keyword_top_k": 10,
  "final_top_k": 5,
  "semantic_weight": 0.65,
  "keyword_weight": 0.35,
  "enable_rerank": false,
  "pre_rerank_top_k": 20,
  "collection_name": "active0",
  "embedding_model_path": "./models/embedding",
  "reranker_model_path": "./models/reranker",
  "query_prefix": "Represent this sentence: "
}
""".strip()
    )

    exit_code = main(["--persist-dir", str(tmp_path), "backup"])

    captured = capsys.readouterr()
    backup_dir = tmp_path.parent / "backup"
    backup_files = sorted(backup_dir.glob("db_*.bak"))
    assert exit_code == 0
    assert len(backup_files) == 1
    assert backup_files[0].name.startswith("db_")
    assert backup_files[0].suffix == ".bak"
    assert "Backed up active collection 'active0'" in captured.out
    with zipfile.ZipFile(backup_files[0]) as archive:
        members = set(archive.namelist())
    assert "chroma.sqlite3" in members
    assert "config.json" in members


def test_backup_fails_when_active_collection_is_missing_from_persist_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _create_empty_collection(tmp_path, "active0")

    exit_code = main(["--persist-dir", str(tmp_path), "backup"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Active configured collection 'rag_collection' does not exist" in captured.err


def test_set_environment_updates_env_file_and_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _create_empty_collection(tmp_path, "active0")
    env_file = tmp_path / ".env"

    exit_code = main(
        [
            "--persist-dir",
            str(tmp_path),
            "set-environment",
            "active0",
            "--env-file",
            str(env_file),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Updated environment file" in captured.out
    env_text = env_file.read_text()
    assert "MCP_HOST=127.0.0.1" in env_text
    assert "MCP_TRANSPORT=http" in env_text
    assert "MCP_PORT=8001" in env_text
    assert "COLLECTION_NAME=active0" in env_text
    config_text = (tmp_path / "config.json").read_text()
    assert '"collection_name": "active0"' in config_text


def test_set_environment_rejects_unknown_collection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _create_empty_collection(tmp_path, "active0")

    exit_code = main(["--persist-dir", str(tmp_path), "set-environment", "missing0"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "does not exist" in captured.err


def test_model_backup_uses_model_type_prefix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    embedding_dir = tmp_path / "models" / "embedding"
    custom_embed_dir = tmp_path / "models" / "custom_embed"
    reranker_dir = tmp_path / "models" / "reranker"
    embedding_dir.mkdir(parents=True, exist_ok=True)
    custom_embed_dir.mkdir(parents=True, exist_ok=True)
    reranker_dir.mkdir(parents=True, exist_ok=True)
    (embedding_dir / "config.json").write_text("st")
    (custom_embed_dir / "README.md").write_text("custom-st")
    (reranker_dir / "model.safetensors").write_text("ce")

    (tmp_path / "config.json").write_text(
        (
            "{" 
            '"semantic_top_k": 10,'
            '"keyword_top_k": 10,'
            '"final_top_k": 5,'
            '"semantic_weight": 0.65,'
            '"keyword_weight": 0.35,'
            '"enable_rerank": false,'
            '"pre_rerank_top_k": 20,'
            '"collection_name": "active0",'
            f'"embedding_model_path": "{embedding_dir}",'
            f'"reranker_model_path": "{reranker_dir}",'
            '"query_prefix": "Represent this sentence: "'
            "}"
        )
    )

    exit_code = main(["--persist-dir", str(tmp_path), "model-backup", "st"])

    captured = capsys.readouterr()
    backup_dir = tmp_path.parent / "backup"
    backup_files = sorted(backup_dir.glob("st_*.bak"))
    assert exit_code == 0
    assert "Backed up sentence transformer model directories" in captured.out
    assert len(backup_files) == 1
    with zipfile.ZipFile(backup_files[0]) as archive:
        members = set(archive.namelist())
    assert "models/embedding/config.json" in members
    assert "models/custom_embed/README.md" in members


def test_model_backup_cross_encoder_uses_model_type_prefix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    embedding_dir = tmp_path / "models" / "embedding"
    reranker_dir = tmp_path / "models" / "reranker"
    embedding_dir.mkdir(parents=True, exist_ok=True)
    reranker_dir.mkdir(parents=True, exist_ok=True)
    (reranker_dir / "model.safetensors").write_text("ce")

    (tmp_path / "config.json").write_text(
        (
            "{" 
            '"semantic_top_k": 10,'
            '"keyword_top_k": 10,'
            '"final_top_k": 5,'
            '"semantic_weight": 0.65,'
            '"keyword_weight": 0.35,'
            '"enable_rerank": false,'
            '"pre_rerank_top_k": 20,'
            '"collection_name": "active0",'
            f'"embedding_model_path": "{embedding_dir}",'
            f'"reranker_model_path": "{reranker_dir}",'
            '"query_prefix": "Represent this sentence: "'
            "}"
        )
    )

    exit_code = main(["--persist-dir", str(tmp_path), "model-backup", "ce"])

    captured = capsys.readouterr()
    backup_dir = tmp_path.parent / "backup"
    backup_files = sorted(backup_dir.glob("ce_*.bak"))
    assert exit_code == 0
    assert "Backed up cross encoder model directory" in captured.out
    assert len(backup_files) == 1
    with zipfile.ZipFile(backup_files[0]) as archive:
        members = set(archive.namelist())
    assert "model.safetensors" in members


def test_model_backup_requires_model_type_argument(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--persist-dir", str(tmp_path), "model-backup"])

    assert exc_info.value.code == 2


def test_restore_uses_latest_db_backup_and_replaces_persist_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backup_dir = tmp_path / "backup"
    _write_backup_archive(
        backup_dir,
        "db_05_06_26_10_00_00.bak",
        {
            "chroma.sqlite3": b"olddb",
            "state.txt": b"older",
        },
    )
    _write_backup_archive(
        backup_dir,
        "db_05_07_26_10_00_00.bak",
        {
            "chroma.sqlite3": b"newdb",
            "state.txt": b"latest",
        },
    )
    (tmp_path / "state.txt").write_text("current")

    exit_code = main(
        [
            "--persist-dir",
            str(tmp_path),
            "restore",
            "--backup-dir",
            str(backup_dir),
            "--force",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Restored vector DB" in captured.out
    assert (tmp_path / "state.txt").read_text() == "latest"



def test_restore_prompt_includes_source_target_and_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    backup_dir = tmp_path / "backup"
    latest_backup = _write_backup_archive(
        backup_dir,
        "db_05_07_26_10_00_00.bak",
        {
            "chroma.sqlite3": b"newdb",
        },
    )

    prompts: list[str] = []

    def _fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "n"

    monkeypatch.setattr("builtins.input", _fake_input)

    exit_code = main(
        [
            "--persist-dir",
            str(tmp_path),
            "restore",
            "--backup-dir",
            str(backup_dir),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "Restore cancelled."
    assert prompts == [
        "Restore will replace the existing vector DB data.\n"
        f"Source: {latest_backup}\n"
        f"Target:\n  - {tmp_path.resolve()}\n"
        "Backup timestamp: 2026-05-07 10:00:00\n"
        "This cannot be undone. Continue? [y/N]: "
    ]



def test_restore_returns_not_found_when_db_backup_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backup_dir = tmp_path / "backup"
    exit_code = main(
        [
            "--persist-dir",
            str(tmp_path),
            "restore",
            "--backup-dir",
            str(backup_dir),
            "--force",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "no DB backup found" in captured.err


def test_model_restore_uses_latest_sentence_transformer_backup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    embedding_dir = tmp_path / "models" / "embedding"
    custom_embed_dir = tmp_path / "models" / "custom_embed"
    reranker_dir = tmp_path / "models" / "reranker"
    embedding_dir.mkdir(parents=True, exist_ok=True)
    custom_embed_dir.mkdir(parents=True, exist_ok=True)
    reranker_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text(
        (
            "{" 
            '"semantic_top_k": 10,'
            '"keyword_top_k": 10,'
            '"final_top_k": 5,'
            '"semantic_weight": 0.65,'
            '"keyword_weight": 0.35,'
            '"enable_rerank": false,'
            '"pre_rerank_top_k": 20,'
            '"collection_name": "active0",'
            f'"embedding_model_path": "{embedding_dir}",'
            f'"reranker_model_path": "{reranker_dir}",'
            '"query_prefix": "Represent this sentence: "'
            "}"
        )
    )
    backup_dir = tmp_path / "backup"
    _write_backup_archive(
        backup_dir,
        "st_05_06_26_09_00_00.bak",
        {
            "models/embedding/marker.txt": b"older",
            "models/custom_embed/README.md": b"older-custom",
        },
    )
    _write_backup_archive(
        backup_dir,
        "st_05_07_26_09_00_00.bak",
        {
            "models/embedding/marker.txt": b"latest-st",
            "models/custom_embed/README.md": b"latest-custom",
        },
    )

    exit_code = main(
        [
            "--persist-dir",
            str(tmp_path),
            "model-restore",
            "st",
            "--backup-dir",
            str(backup_dir),
            "--force",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Restored sentence transformer backup" in captured.out
    assert (embedding_dir / "marker.txt").read_text() == "latest-st"
    assert (custom_embed_dir / "README.md").read_text() == "latest-custom"


def test_model_restore_returns_sentence_transformer_not_found_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    embedding_dir = tmp_path / "models" / "embedding"
    reranker_dir = tmp_path / "models" / "reranker"
    embedding_dir.mkdir(parents=True, exist_ok=True)
    reranker_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text(
        (
            "{" 
            '"semantic_top_k": 10,'
            '"keyword_top_k": 10,'
            '"final_top_k": 5,'
            '"semantic_weight": 0.65,'
            '"keyword_weight": 0.35,'
            '"enable_rerank": false,'
            '"pre_rerank_top_k": 20,'
            '"collection_name": "active0",'
            f'"embedding_model_path": "{embedding_dir}",'
            f'"reranker_model_path": "{reranker_dir}",'
            '"query_prefix": "Represent this sentence: "'
            "}"
        )
    )
    backup_dir = tmp_path / "backup"
    exit_code = main(
        [
            "--persist-dir",
            str(tmp_path),
            "model-restore",
            "st",
            "--backup-dir",
            str(backup_dir),
            "--force",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "no sentence transformer backup found" in captured.err


def test_model_restore_returns_cross_encoder_not_found_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    embedding_dir = tmp_path / "models" / "embedding"
    reranker_dir = tmp_path / "models" / "reranker"
    embedding_dir.mkdir(parents=True, exist_ok=True)
    reranker_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text(
        (
            "{" 
            '"semantic_top_k": 10,'
            '"keyword_top_k": 10,'
            '"final_top_k": 5,'
            '"semantic_weight": 0.65,'
            '"keyword_weight": 0.35,'
            '"enable_rerank": false,'
            '"pre_rerank_top_k": 20,'
            '"collection_name": "active0",'
            f'"embedding_model_path": "{embedding_dir}",'
            f'"reranker_model_path": "{reranker_dir}",'
            '"query_prefix": "Represent this sentence: "'
            "}"
        )
    )
    backup_dir = tmp_path / "backup"
    exit_code = main(
        [
            "--persist-dir",
            str(tmp_path),
            "model-restore",
            "ce",
            "--backup-dir",
            str(backup_dir),
            "--force",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "no cross encoder backup found" in captured.err


def test_model_restore_rejects_unsafe_archive_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    embedding_dir = tmp_path / "models" / "embedding"
    reranker_dir = tmp_path / "models" / "reranker"
    embedding_dir.mkdir(parents=True, exist_ok=True)
    reranker_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text(
        (
            "{" 
            '"semantic_top_k": 10,'
            '"keyword_top_k": 10,'
            '"final_top_k": 5,'
            '"semantic_weight": 0.65,'
            '"keyword_weight": 0.35,'
            '"enable_rerank": false,'
            '"pre_rerank_top_k": 20,'
            '"collection_name": "active0",'
            f'"embedding_model_path": "{embedding_dir}",'
            f'"reranker_model_path": "{reranker_dir}",'
            '"query_prefix": "Represent this sentence: "'
            "}"
        )
    )
    backup_dir = tmp_path / "backup"
    _write_backup_archive(
        backup_dir,
        "st_05_07_26_12_00_00.bak",
        {
            "../escape.txt": b"bad",
            "marker.txt": b"db",
        },
    )
    (embedding_dir / "keep.txt").write_text("safe")

    exit_code = main(
        [
            "--persist-dir",
            str(tmp_path),
            "model-restore",
            "st",
            "--backup-dir",
            str(backup_dir),
            "--force",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Restore failed" in captured.err
    assert (embedding_dir / "keep.txt").read_text() == "safe"
