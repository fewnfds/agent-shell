from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import weakref

from langgraph.checkpoint.memory import PersistentDict
import pytest

from agent_shell import langgraph_dev_persistence as persistence
from agent_shell.storage import atomic_files


@pytest.mark.parametrize("write_if_changed", [True, False])
def test_snapshot_writes_follow_policy_and_restore_nested_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_if_changed: bool
) -> None:
    path = tmp_path / "core.pckl"
    store = PersistentDict(filename=str(path))
    store["threads"] = [{"metadata": {"label": "initial"}}]
    commits = []
    replace = atomic_files.os.replace

    def record_replace(source, destination):
        commits.append(destination)
        replace(source, destination)

    monkeypatch.setattr(atomic_files.os, "replace", record_replace)
    writer = persistence._SnapshotWriter(
        store, persistence.LangGraphPersistenceSettings(write_if_changed=write_if_changed)
    )
    writer.sync()
    writer.sync()
    assert len(commits) == (1 if write_if_changed else 2)
    store["threads"][0]["metadata"]["label"] = "changed"
    writer.sync()
    restored = PersistentDict(filename=str(path))
    restored.load()
    assert restored["threads"] == [{"metadata": {"label": "changed"}}]
    store.clear()
    writer.sync()
    restored.clear()
    restored.load()
    assert dict(restored) == {}
    assert len(commits) == (3 if write_if_changed else 4)


def test_flush_uses_configured_interval_retries_failed_commit_and_saves_on_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    from langgraph_runtime_inmem import _persistence, database

    store = PersistentDict(filename=str(tmp_path / "core.pckl"))
    retry = PersistentDict(int, filename=str(tmp_path / "retry.pckl"))
    store["threads"] = ["saved"]
    persistence._SnapshotWriter(store, persistence.LangGraphPersistenceSettings()).sync()
    previous = Path(store.filename).read_bytes()
    store["threads"].append("pending")
    monkeypatch.setattr(database, "GLOBAL_STORE", store)
    monkeypatch.setattr(database, "GLOBAL_RETRY_COUNTER", SimpleNamespace(_counters=retry))
    monkeypatch.setattr(_persistence, "_stores", {store.filename: weakref.ref(store), retry.filename: weakref.ref(retry)})
    attempts = 0
    replace = atomic_files.os.replace

    def fail_first_replace(source, destination):
        nonlocal attempts
        if Path(destination) == Path(store.filename):
            attempts += 1
            if attempts == 1:
                raise OSError("injected replace failure")
        replace(source, destination)

    monkeypatch.setattr(atomic_files.os, "replace", fail_first_replace)
    waits = []

    class StopEvent:
        def wait(self, timeout):
            waits.append(timeout)
            if len(waits) == 2:
                assert Path(store.filename).read_bytes() == previous
            return len(waits) > 2

    policy = persistence.LangGraphPersistenceSettings(flush_interval_seconds=37)
    with persistence.configured_dev_persistence(policy):
        _persistence._flush_loop(StopEvent())
        assert waits == [37, 37, 37]
        assert attempts == 2
        assert "retrying next interval" in caplog.text
        assert Path(retry.filename).exists()  # An empty registered store is also saved.
        store["threads"].append("shutdown")
        store.close()  # Keep the official close -> sync -> clear path.
    restored = PersistentDict(filename=store.filename)
    restored.load()
    assert restored["threads"] == ["saved", "pending", "shutdown"]
    assert not list(tmp_path.glob("*.tmp"))


def test_unreviewed_dependency_version_stops_persistence_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(persistence, "version", lambda _package: "99.0.0")
    with pytest.raises(RuntimeError, match="docs/langgraph-dev-customizations.md"):
        with persistence.configured_dev_persistence(persistence.LangGraphPersistenceSettings()):
            pytest.fail("unreviewed dependency was accepted")
