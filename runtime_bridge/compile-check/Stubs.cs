using System;

namespace BepInEx
{
    [AttributeUsage(AttributeTargets.Class)]
    public sealed class BepInPlugin : Attribute
    {
        public BepInPlugin(string guid, string name, string version) { }
    }

    public class BaseUnityPlugin
    {
        public BepInEx.Logging.ManualLogSource Logger { get; } = new();
    }
}

namespace BepInEx.Logging
{
    public sealed class ManualLogSource
    {
        public void LogInfo(object message) { }
        public void LogError(object message) { }
    }
}

namespace UnityEngine
{
    public static class Application
    {
        public static string version => "compile-check";
    }

    public static class Time
    {
        public static float unscaledTime => 0f;
    }
}

namespace System.Web.Script.Serialization
{
    public sealed class JavaScriptSerializer
    {
        public string Serialize(object value) => "{}";
    }
}
