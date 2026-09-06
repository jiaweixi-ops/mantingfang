using System;
using BepInEx;
using BepInEx.Logging;
using UnityEngine;

namespace MantingfangTelemetryBridge;

[BepInPlugin("jiaweixi-ops.mantingfang.telemetry", "Mantingfang Read-only Telemetry", "0.1.0")]
public sealed class Plugin : BaseUnityPlugin
{
    private TelemetryServer? server;
    private readonly ReadOnlyStateReader reader = new();

    private void Awake()
    {
        server = new TelemetryServer(Logger, 18765);
        server.Start();
        Logger.LogInfo("Mantingfang read-only telemetry bridge started on loopback:18765");
    }

    private void Update()
    {
        try
        {
            // Unity objects are sampled only from the Unity main thread. The
            // HTTP worker receives the last immutable serialized snapshot.
            server?.Publish(reader.Read());
        }
        catch (Exception ex)
        {
            Logger.LogError($"telemetry main-thread sample failed: {ex.GetType().Name}");
            server?.Publish(ReadOnlyStateReader.Unknown("main_thread_sample_failed"));
        }
    }

    private void OnDestroy()
    {
        server?.Dispose();
        server = null;
    }
}
