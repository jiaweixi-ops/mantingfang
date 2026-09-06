using BepInEx;
using BepInEx.Logging;
using UnityEngine;

namespace MantingfangTelemetryBridge;

[BepInPlugin("jiaweixi-ops.mantingfang.telemetry", "Mantingfang Read-only Telemetry", "0.1.0")]
public sealed class Plugin : BaseUnityPlugin
{
    private TelemetryServer? server;

    private void Awake()
    {
        server = new TelemetryServer(Logger, 18765);
        server.Start();
        Logger.LogInfo("Mantingfang read-only telemetry bridge started on loopback:18765");
    }

    private void OnDestroy()
    {
        server?.Dispose();
        server = null;
    }
}
