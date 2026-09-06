using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;
using UnityEngine;

namespace MantingfangTelemetryBridge;

internal sealed class ReadOnlyStateReader
{
    private static readonly string[] RootTypeNames = { "RootData", "DataComponent", "BaseData" };

    public object Read()
    {
        object? root = FindRoot();
        if (root is null)
            return Unknown("validated_root_instance_not_found");

        object? baseData = GetMember(root, "BaseData") ?? (TypeName(root) == "BaseData" ? root : null);
        object? sceneData = GetMember(root, "SceneData");
        if (baseData is null || sceneData is null)
            return Unknown("BaseData_or_SceneData_not_verified");

        object? resources = GetMember(baseData, "ShowRes");
        object? villagers = GetMember(baseData, "Villagers");
        object? buildings = GetMember(sceneData, "Buildings");
        object? sites = GetMember(sceneData, "Sites");
        if (resources is null || villagers is null || buildings is null || sites is null)
            return Unknown("required_state_members_not_verified");

        return new Dictionary<string, object?>
        {
            ["source"] = "runtime_bridge",
            ["status"] = "OK",
            ["game_pid"] = Process.GetCurrentProcess().Id,
            ["game_version"] = Application.version,
            ["observed_at"] = DateTime.UtcNow.ToString("O"),
            ["city_name"] = GetMember(baseData, "CityName"),
            ["year"] = GetMember(baseData, "Year"),
            ["month"] = GetMember(baseData, "Month"),
            ["gold"] = FindResource(resources, 2),
            ["population"] = Count(villagers),
            ["resources"] = ReadResources(resources),
            ["buildings_count"] = Count(buildings),
            ["sites_count"] = Count(sites),
            ["build_menu_open"] = ReadBuildMenuOpen(),
        };
    }

    private static Dictionary<string, object?> ReadResources(object resources)
    {
        var result = new Dictionary<string, object?>();
        foreach (object item in Enumerate(resources))
        {
            object? id = GetMember(item, "Id") ?? GetMember(item, "ResId");
            object? amount = GetMember(item, "Num") ?? GetMember(item, "Count") ?? GetMember(item, "Value");
            if (id is null || amount is null) continue;
            result[$"res_{id}"] = amount;
        }
        return result;
    }

    private static object? FindResource(object resources, int wantedId)
    {
        foreach (object item in Enumerate(resources))
        {
            object? id = GetMember(item, "Id") ?? GetMember(item, "ResId");
            if (id is not null && Convert.ToInt32(id) == wantedId)
                return GetMember(item, "Num") ?? GetMember(item, "Count") ?? GetMember(item, "Value");
        }
        return null;
    }

    private static object? ReadBuildMenuOpen()
    {
        Type? type = FindType("UIBuildMenuViewCtrl");
        object? instance = type is null ? null : FindSingleton(type);
        if (instance is null) return null;
        return GetMember(instance, "IsOpen") ?? GetMember(instance, "isOpen") ?? GetMember(instance, "Open");
    }

    private static object Unknown(string reason) => new Dictionary<string, object?>
    {
        ["source"] = "runtime_bridge", ["status"] = "UNKNOWN", ["reason"] = reason,
        ["game_pid"] = Process.GetCurrentProcess().Id, ["game_version"] = Application.version,
        ["observed_at"] = DateTime.UtcNow.ToString("O"),
    };

    private static object? FindRoot()
    {
        foreach (string name in RootTypeNames)
        {
            Type? type = FindType(name);
            if (type is not null)
            {
                object? instance = FindSingleton(type);
                if (instance is not null) return instance;
            }
        }
        return null;
    }

    private static Type? FindType(string name) => AppDomain.CurrentDomain.GetAssemblies()
        .SelectMany(SafeTypes).FirstOrDefault(type => type.Name == name || type.FullName == $"WSFramework.{name}");

    private static IEnumerable<Type> SafeTypes(Assembly assembly)
    {
        try { return assembly.GetTypes(); } catch (ReflectionTypeLoadException ex) { return ex.Types.Where(type => type is not null)!; }
    }

    private static object? FindSingleton(Type type)
    {
        foreach (string name in new[] { "Instance", "instance", "Current", "Data", "RootData" })
        {
            PropertyInfo? property = type.GetProperty(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            if (property is not null && property.GetIndexParameters().Length == 0)
            {
                try { if (property.GetValue(null) is object value) return value; } catch { }
            }
            FieldInfo? field = type.GetField(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            if (field is not null)
            {
                try { if (field.GetValue(null) is object value) return value; } catch { }
            }
        }
        return null;
    }

    private static object? GetMember(object target, string name)
    {
        Type type = target.GetType();
        try
        {
            PropertyInfo? property = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (property is not null && property.GetIndexParameters().Length == 0) return property.GetValue(target);
            FieldInfo? field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            return field?.GetValue(target);
        }
        catch { return null; }
    }

    private static string TypeName(object value) => value.GetType().Name;

    private static int Count(object value) => value is ICollection collection ? collection.Count : Enumerate(value).Count();

    private static IEnumerable<object> Enumerate(object value)
    {
        if (value is IEnumerable enumerable)
            foreach (object? item in enumerable) if (item is not null) yield return item;
    }
}
