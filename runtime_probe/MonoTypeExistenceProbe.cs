using System;
using System.Net;
using Mono.Debugger.Soft;

internal static class Program
{
    private const int DebugPort = 10000;

    private static int Main()
    {
        VirtualMachine machine = null;
        AssemblyMirror unityModel = null;
        AssemblyMirror assemblyCSharp = null;
        var connected = false;
        var disconnected = false;
        var baseDataExists = false;
        var sceneDataExists = false;
        var rootDataExists = false;
        var buildMenuViewExists = false;
        string errorType = null;

        try
        {
            machine = VirtualMachineManager.Connect(
                new IPEndPoint(IPAddress.Loopback, DebugPort));
            connected = true;

            foreach (var assembly in machine.RootDomain.GetAssemblies())
            {
                var simpleName = assembly.GetName().Name ?? string.Empty;
                if (string.Equals(simpleName, "Unity.Model", StringComparison.Ordinal))
                {
                    unityModel = assembly;
                }
                else if (string.Equals(simpleName, "Assembly-CSharp", StringComparison.Ordinal))
                {
                    assemblyCSharp = assembly;
                }
            }

            baseDataExists = TypeExists(unityModel, "WSFramework.BaseData");
            sceneDataExists = TypeExists(unityModel, "WSFramework.SceneData");
            rootDataExists = TypeExists(unityModel, "WSFramework.RootData");
            buildMenuViewExists = TypeExists(assemblyCSharp, "UIBuildMenuViewCtrl");
        }
        catch (Exception error)
        {
            errorType = error.GetType().FullName;
        }
        finally
        {
            if (machine != null)
            {
                try
                {
                    machine.Disconnect();
                    disconnected = true;
                }
                catch (Exception error)
                {
                    if (errorType == null)
                    {
                        errorType = error.GetType().FullName;
                    }
                }
            }
        }

        Console.WriteLine("CONNECTED\t" + connected);
        Console.WriteLine("UNITY_MODEL_ASSEMBLY\t" + (unityModel != null));
        Console.WriteLine("ASSEMBLY_CSHARP_ASSEMBLY\t" + (assemblyCSharp != null));
        Console.WriteLine("TYPE\tWSFramework.BaseData\t" + baseDataExists);
        Console.WriteLine("TYPE\tWSFramework.SceneData\t" + sceneDataExists);
        Console.WriteLine("TYPE\tWSFramework.RootData\t" + rootDataExists);
        Console.WriteLine("TYPE\tUIBuildMenuViewCtrl\t" + buildMenuViewExists);
        Console.WriteLine("TYPE_LOOKUPS\t4");
        Console.WriteLine("DISCONNECTED\t" + disconnected);
        Console.WriteLine("INSTANCE_ENUMERATIONS\t0");
        Console.WriteLine("FIELD_READS\t0");
        Console.WriteLine("PROPERTY_READS\t0");
        Console.WriteLine("VALUE_READS\t0");
        Console.WriteLine("METHOD_INVOCATIONS\t0");
        Console.WriteLine("BREAKPOINTS\t0");
        Console.WriteLine("SUSPENDS\t0");
        Console.WriteLine("WRITES\t0");

        if (errorType != null)
        {
            Console.WriteLine("ERROR_TYPE\t" + errorType);
        }

        return connected && disconnected && errorType == null ? 0 : 2;
    }

    private static bool TypeExists(AssemblyMirror assembly, string fullName)
    {
        return assembly != null && assembly.GetType(fullName, false, false) != null;
    }
}
