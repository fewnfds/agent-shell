from __future__ import annotations

from .support import *


def test_configuration_validation_settings_are_persistent_and_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        initial = client.get("/agent-shell/api/validation/settings")
        saved = client.put(
            "/agent-shell/api/validation/settings",
            json={"debounce_ms": 500},
        )
        reloaded = client.get("/agent-shell/api/validation/settings")
        too_small = client.put(
            "/agent-shell/api/validation/settings",
            json={"debounce_ms": 99},
        )
        large = client.put(
            "/agent-shell/api/validation/settings",
            json={"debounce_ms": 10_001},
        )

    assert initial.status_code == 200
    assert initial.json() == {
        "debounce_ms": 1000,
        "min_debounce_ms": 100,
    }
    assert saved.status_code == 200
    assert saved.json()["debounce_ms"] == 500
    assert reloaded.json()["debounce_ms"] == 500
    assert too_small.status_code == 422
    assert large.status_code == 200
