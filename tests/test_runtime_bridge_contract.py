from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bridge_reads_verified_inventory_from_center_store() -> None:
    source = (ROOT / "runtime_bridge" / "ReadOnlyStateReader.cs").read_text(encoding="utf-8")
    assert 'GetMember(baseData, "CenterStoreData")' in source
    assert 'GetMember(centerStoreData, "Res")' in source
    assert 'GetMember(baseData, "ShowRes")' not in source
    assert '["rice"] = rice' in source
    assert '["vegetable"] = vegetable' in source
    assert '["wood"] = wood' in source
    assert '["stone"] = stone' in source


def test_bridge_samples_unity_on_main_thread_and_serves_cached_json() -> None:
    plugin = (ROOT / "runtime_bridge" / "Plugin.cs").read_text(encoding="utf-8")
    server = (ROOT / "runtime_bridge" / "TelemetryServer.cs").read_text(encoding="utf-8")
    assert "private void Update()" in plugin
    assert "SampleIntervalSeconds = 0.25f" in plugin
    assert "Time.unscaledTime" in plugin
    assert "server?.Publish(reader.Read())" in plugin
    assert "latestStateJson" in server
    assert "reader.Read()" not in server
    assert "WriteJson(context.Response, snapshotJson, 200)" in server


def test_bridge_caches_reflection_metadata() -> None:
    source = (ROOT / "runtime_bridge" / "ReadOnlyStateReader.cs").read_text(encoding="utf-8")
    assert "typeCache" in source
    assert "memberCache" in source
    assert "singletonAccessorCache" in source
