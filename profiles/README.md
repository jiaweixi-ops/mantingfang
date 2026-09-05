# Read-only memory profiles

A profile is intentionally user-maintained because game updates can change module names, pointer chains, and field locations. Do not guess values and do not commit a real profile until it has been validated against the exact installed game build.

Example shape:

```json
{
  "process_name": "<exact-game-process>.exe",
  "pointer_size": 8,
  "fields": {
    "population": {
      "type": "int32",
      "module": "<module-name>.dll",
      "base_offset": "0x0",
      "offsets": ["0x0", "0x0"]
    }
  }
}
```

The sampler only performs `OpenProcess` with query/read access, resolves the configured pointer path, reads the configured scalar type, and closes the handle. It does not scan arbitrary memory, infer addresses, or write process memory.
