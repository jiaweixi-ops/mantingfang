from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime_probe" / "MonoTypeExistenceProbe.cs"
PROJECT = ROOT / "runtime_probe" / "MonoTypeExistenceProbe.csproj"
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


def test_probe_is_fixed_to_four_exact_type_existence_queries() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    assert source.count("VirtualMachineManager.Connect(") == 1
    assert source.count("RootDomain.GetAssemblies()") == 1
    assert source.count("assembly.GetName()") == 1
    assert source.count("assembly.GetType(fullName, false, false)") == 1
    assert source.count("TypeExists(") == 5  # definition plus four fixed calls
    assert source.count("machine.Disconnect()") == 1
    assert source.count("Console.Out.Flush()") == 1
    assert 'Marker("CONNECT_BEGIN")' in source
    assert 'Marker("DISCONNECT_BEGIN")' in source
    assert "IPAddress.Loopback" in source
    assert "DebugPort = 10000" in source

    required = (
        ("WSFramework.BaseData", "unityModel"),
        ("WSFramework.SceneData", "unityModel"),
        ("WSFramework.RootData", "unityModel"),
        ("UIBuildMenuViewCtrl", "assemblyCSharp"),
    )
    for type_name, assembly_variable in required:
        assert f'TypeExists({assembly_variable}, "{type_name}")' in source


def test_probe_excludes_runtime_state_and_mutating_debugger_apis() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    forbidden = (
        ".Suspend(",
        ".Resume(",
        "CreateBreakpoint",
        "SetBreakpoint",
        "CreateStep",
        "CreateExceptionRequest",
        "BeginConnect",
        "machine.GetTypes(",
        ".GetTypesForSourceFile(",
        ".ManifestModule",
        ".GetMetadata(",
        ".GetAssemblyObject(",
        ".GetFields(",
        ".GetField(",
        ".GetProperties(",
        ".GetProperty(",
        ".GetValue(",
        ".SetValue(",
        ".Invoke(",
        "GetThreads",
        "GetFrames",
        "GetLocal",
        "GetStack",
        "ObjectMirror",
        "ThreadMirror",
        "FieldInfoMirror",
        "PropertyInfoMirror",
        "MethodMirror",
        "InvokeOptions",
        "while (",
        "for (;;)",
    )
    for token in forbidden:
        assert token not in source


def test_probe_build_is_pinned_and_published_by_ci() -> None:
    project = PROJECT.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "<TargetFramework>net472</TargetFramework>" in project
    assert 'Include="Mono.Debugger.Soft" Version="1.0.20170212.42"' in project
    assert "Microsoft.NETFramework.ReferenceAssemblies.net472" in project
    assert "MonoTypeExistenceProbe.cs" in project
    assert "dotnet publish runtime_probe/MonoTypeExistenceProbe.csproj" in workflow
    assert "MonoTypeExistenceProbe" in workflow
