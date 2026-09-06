from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime_probe" / "MonoAssemblyEnumerator.cs"
PROJECT = ROOT / "runtime_probe" / "MonoAssemblyEnumerator.csproj"
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


def test_enumerator_has_only_the_minimal_read_only_debugger_path() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    assert source.count("VirtualMachineManager.Connect(") == 1
    assert source.count("RootDomain.GetAssemblies()") == 1
    assert source.count("assembly.GetName()") == 1
    assert source.count("machine.Disconnect()") == 1
    assert "IPAddress.Loopback" in source
    assert "DebugPort = 10000" in source

    forbidden = (
        ".Suspend(",
        ".Resume(",
        "CreateBreakpoint",
        "SetBreakpoint",
        "CreateStep",
        "CreateExceptionRequest",
        "BeginConnect",
        "GetTypes",
        "GetThreads",
        "GetFrames",
        "GetValue",
        "SetValue",
        "ObjectMirror",
        "ThreadMirror",
        "FieldInfoMirror",
        "MethodMirror",
        "InvokeOptions",
        "while (",
        "for (;;)",
    )
    for token in forbidden:
        assert token not in source


def test_enumerator_build_is_pinned_and_published_by_ci() -> None:
    project = PROJECT.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "<TargetFramework>net472</TargetFramework>" in project
    assert 'Include="Mono.Debugger.Soft" Version="1.0.20170212.42"' in project
    assert "Microsoft.NETFramework.ReferenceAssemblies.net472" in project
    assert "MonoAssemblyEnumerator.cs" in project
    assert "dotnet publish runtime_probe/MonoAssemblyEnumerator.csproj" in workflow
    assert "MonoAssemblyEnumerator" in workflow
