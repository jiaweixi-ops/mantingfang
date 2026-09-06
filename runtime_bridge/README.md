# Read-only Unity/Mono telemetry bridge

This directory documents the optional local bridge consumed by
`ai_governor.telemetry.RuntimeTelemetryClient`. It is deliberately not an
automatic injector and it does not contain game-specific guessed addresses.

The bridge must expose two local HTTP endpoints on `127.0.0.1:18765`:

```text
GET /health
GET /state
```

`/state` must return either a complete, verified snapshot or an explicit
`UNKNOWN`/`BLOCKED` response. The Governor must never interpret missing fields,
zero values, or placeholder values as facts. A valid snapshot has this shape:

```json
{
  "source": "runtime_bridge",
  "status": "OK",
  "game_pid": 26320,
  "game_version": "<local version>",
  "city_name": "新的城市",
  "year": 1,
  "month": 4,
  "gold": 1000,
  "population": 10,
  "resources": {
    "rice": 50,
    "vegetable": 50,
    "wood": 100,
    "stone": 100
  },
  "buildings_count": 1,
  "sites_count": 0,
  "build_menu_open": false,
  "observed_at": "2026-09-06T00:00:00Z"
}
```

The implementation must satisfy these constraints:

- read-only reflection/telemetry only; no `WriteProcessMemory`, save writes,
  input injection, or action endpoints;
- resolve `BaseData`, `SceneData`, `RootData`, `DataComponent`, and
  `UIBuildMenuViewCtrl` only when a real instance exists;
- return `UNKNOWN` when a field cannot be verified for the running game build;
- include the process id and game version so the Python side can reject stale
  snapshots;
- include an ISO-8601 `observed_at` timestamp; the Python side rejects snapshots
  older than two seconds by default and rejects PID/version mismatches;
- read the verified inventory from `BaseData.CenterStoreData.Res` using the
  validated IDs `2/3/4/8/9` for gold/rice/vegetable/wood/stone; `ShowRes` is
  not the inventory source;
- publish only complete `status=OK` snapshots; any null, missing, or invalid
  core value must produce `UNKNOWN`;
- sample Unity objects from `Plugin.Update` on the Unity main thread and let
  the HTTP worker return only the last serialized snapshot;
- sample at a bounded 4 Hz interval by default and cache discovered types,
  members, and singleton accessors; do not scan all loaded assemblies every
  frame;
- bind to loopback only and keep the HTTP surface to `/health` and `/state`;
- do not log API keys, Feishu credentials, save contents, or full game objects.

The repository includes `Plugin.cs`, `TelemetryServer.cs`, and
`ReadOnlyStateReader.cs` as the reference implementation. Build it only after
setting `BepInExPath` and `UnityManagedPath` to the exact local game-version
assemblies, for example:

```powershell
dotnet build .\runtime_bridge\MantingfangTelemetryBridge.csproj `
  -p:BepInExPath='C:\path\to\BepInEx' `
  -p:UnityManagedPath='F:\SteamLibrary\steamapps\common\Thriving City Song\Song_Data\Managed'
```

The repository also contains a dependency-free source compile check at
`runtime_bridge/compile-check/`. It compiles the three bridge source files
against minimal BepInEx/Unity/serializer stubs so CI can catch C# errors such as
static/instance mismatches without pretending that the exact game assemblies
are available. This check validates source syntax and contracts only; it does
not build or inject a production plugin.

The current installation has not been injected or modified automatically.
Until this project is built against the exact installed BepInEx/Unity
assemblies and its returned fields are cross-checked against the saved city,
the Python client must remain disabled (`GOVERNOR_RUNTIME_TELEMETRY=false`).
When enabled for a verified build, `GOVERNOR_RUNTIME_GAME_VERSION` is required
and must match the bridge snapshot.

The `telemetry-read` CLI also locates the current Song window, binds the
current Song PID, and requires the configured game version before accepting a
snapshot. Any PID/version/staleness/schema failure returns exit code `2`.

The V5 ZIP supplied during planning contains a reflective bridge prototype, but
it depends on external BepInEx/Unity assemblies and is not a drop-in build for
this installation. It is therefore reference material only until the exact
game version and third-party assembly paths are verified.
