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
- bind to loopback only and keep the HTTP surface to `/health` and `/state`;
- do not log API keys, Feishu credentials, save contents, or full game objects.

The V5 ZIP supplied during planning contains a reflective bridge prototype, but
it depends on external BepInEx/Unity assemblies and is not a drop-in build for
this installation. It is therefore reference material only until the exact
game version and third-party assembly paths are verified.
