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
    assert "private bool TryReadResource" in source
    assert "private static bool TryReadResource" not in source
    assert "if (type is not null)" in source


def test_bridge_compile_check_includes_real_sources_and_ci_step() -> None:
    project = (ROOT / "runtime_bridge" / "compile-check" / "BridgeCompileCheck.csproj").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "..\\Plugin.cs" in project
    assert "..\\TelemetryServer.cs" in project
    assert "..\\ReadOnlyStateReader.cs" in project
    assert "dotnet build runtime_bridge/compile-check/BridgeCompileCheck.csproj" in workflow
