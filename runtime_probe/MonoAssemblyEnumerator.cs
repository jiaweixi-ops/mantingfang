using System;
using System.Collections.Generic;
using System.Net;
using Mono.Debugger.Soft;

internal static class Program
{
    private const int DebugPort = 10000;

    private static int Main()
    {
        VirtualMachine machine = null;
        var assemblies = new List<KeyValuePair<string, string>>();
        var connected = false;
        var disconnected = false;
        string errorType = null;

        try
        {
            machine = VirtualMachineManager.Connect(
                new IPEndPoint(IPAddress.Loopback, DebugPort));
            connected = true;

            foreach (var assembly in machine.RootDomain.GetAssemblies())
            {
                var assemblyName = assembly.GetName();
                var simpleName = assemblyName.Name ?? string.Empty;
                var fullName = assemblyName.FullName ?? simpleName;
                assemblies.Add(new KeyValuePair<string, string>(simpleName, fullName));
            }
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
        Console.WriteLine("ASSEMBLIES_COUNT\t" + assemblies.Count);
        foreach (var assembly in assemblies)
        {
            Console.WriteLine("ASSEMBLY\t" + assembly.Key + "\t" + assembly.Value);
        }
        Console.WriteLine("DISCONNECTED\t" + disconnected);
        Console.WriteLine("FIELD_READS\t0");
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
}
