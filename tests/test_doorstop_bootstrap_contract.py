from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_is_a_noop_doorstop_entrypoint() -> None:
    source = (ROOT / "runtime_probe" / "DoorstopBootstrap.cs").read_text(encoding="utf-8")
    assert "namespace Doorstop" in source
    assert "public static class Entrypoint" in source
    assert "public static void Start()" in source
    assert "using " not in source
    for forbidden in ("BepInEx", "Unity", "Harmony", "Reflection", "Thread", "File", "Http", "Socket"):
        assert forbidden not in source


def test_bootstrap_uses_minimal_net40_contract_and_ci_artifact() -> None:
    project = (ROOT / "runtime_probe" / "DoorstopBootstrap.csproj").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "<TargetFramework>net40</TargetFramework>" in project
    assert "Microsoft.NETFramework.ReferenceAssemblies.net40" in project
    assert "DoorstopBootstrap.cs" in project
    assert "dotnet build runtime_probe/DoorstopBootstrap.csproj" in workflow
    assert "DoorstopTelemetryBootstrap.dll" in workflow
