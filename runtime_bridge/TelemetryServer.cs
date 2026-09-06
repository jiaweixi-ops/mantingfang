using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using BepInEx.Logging;
using UnityEngine;
using System.Web.Script.Serialization;

namespace MantingfangTelemetryBridge;

internal sealed class TelemetryServer : IDisposable
{
    private readonly ManualLogSource log;
    private readonly HttpListener listener = new();
    private readonly int port;
    private readonly ReadOnlyStateReader reader = new();
    private Thread? worker;
    private volatile bool stopping;

    public TelemetryServer(ManualLogSource log, int port)
    {
        this.log = log;
        this.port = port;
    }

    public void Start()
    {
        listener.Prefixes.Add($"http://127.0.0.1:{port}/");
        listener.Start();
        worker = new Thread(Serve) { IsBackground = true, Name = "MantingfangTelemetry" };
        worker.Start();
    }

    private void Serve()
    {
        while (!stopping)
        {
            HttpListenerContext? context = null;
            try { context = listener.GetContext(); }
            catch (HttpListenerException) when (stopping) { break; }
            catch (Exception ex)
            {
                if (!stopping) log.LogError($"telemetry listener failed: {ex.GetType().Name}");
                continue;
            }

            try { Handle(context); }
            catch (Exception ex)
            {
                log.LogError($"telemetry request failed: {ex.GetType().Name}");
                Write(context.Response, new { source = "runtime_bridge", status = "UNKNOWN", reason = "request_failed" }, 500);
            }
        }
    }

    private void Handle(HttpListenerContext context)
    {
        if (context.Request.HttpMethod != "GET")
        {
            Write(context.Response, new { source = "runtime_bridge", status = "BLOCKED", reason = "read_only_get_only" }, 405);
            return;
        }
        if (context.Request.Url?.AbsolutePath == "/health")
        {
            Write(context.Response, new { source = "runtime_bridge", status = "OK" }, 200);
            return;
        }
        if (context.Request.Url?.AbsolutePath == "/state")
        {
            Write(context.Response, reader.Read(), 200);
            return;
        }
        Write(context.Response, new { source = "runtime_bridge", status = "BLOCKED", reason = "unknown_endpoint" }, 404);
    }

    private static void Write(HttpListenerResponse response, object payload, int status)
    {
        string json = new JavaScriptSerializer().Serialize(payload);
        byte[] bytes = Encoding.UTF8.GetBytes(json);
        response.StatusCode = status;
        response.ContentType = "application/json; charset=utf-8";
        response.ContentLength64 = bytes.Length;
        using Stream output = response.OutputStream;
        output.Write(bytes, 0, bytes.Length);
    }

    public void Dispose()
    {
        stopping = true;
        try { listener.Stop(); } catch { }
        try { listener.Close(); } catch { }
        if (worker is { IsAlive: true }) worker.Join(500);
    }
}
