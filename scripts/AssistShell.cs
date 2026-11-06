// Read and set a shortcut's AppUserModelID (used by install-shortcuts.ps1).
//
// The installed Chrome app's window carries Chrome's app ID for it. When our
// "Assist" shortcut has the same ID, Windows treats them as one app: the pinned
// shortcut and the running window share one taskbar button with our icon, and
// clicking it runs the launcher (which starts the API first).
using System;
using System.Runtime.InteropServices;

public static class AssistShell
{
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct PropertyKey { public Guid fmtid; public uint pid; }

    [StructLayout(LayoutKind.Explicit)]
    struct PropVariant { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore
    {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetAt(uint index, out PropertyKey key);
        [PreserveSig] int GetValue(ref PropertyKey key, out PropVariant value);
        [PreserveSig] int SetValue(ref PropertyKey key, ref PropVariant value);
        [PreserveSig] int Commit();
    }

    [ComImport, Guid("0000010b-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPersistFile
    {
        void GetClassID(out Guid id);
        [PreserveSig] int IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string file, uint mode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string file, bool remember);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string file);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string file);
    }

    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    class ShellLink { }

    // PKEY_AppUserModel_ID
    static PropertyKey AppIdKey = new PropertyKey {
        fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };

    /// <summary>The shortcut's AppUserModelID, or "" if it has none.</summary>
    public static string GetShortcutAppId(string lnkPath)
    {
        var link = new ShellLink();
        try
        {
            ((IPersistFile)link).Load(lnkPath, 0 /* STGM_READ */);
            PropVariant v;
            if (((IPropertyStore)link).GetValue(ref AppIdKey, out v) != 0 || v.vt != 31) return "";
            return Marshal.PtrToStringUni(v.p);
        }
        finally { Marshal.ReleaseComObject(link); }
    }

    /// <summary>Give a .lnk file an AppUserModelID.</summary>
    public static void SetShortcutAppId(string lnkPath, string appId)
    {
        var link = new ShellLink();
        try
        {
            var file = (IPersistFile)link;
            file.Load(lnkPath, 2 /* STGM_READWRITE */);
            var store = (IPropertyStore)link;
            var v = new PropVariant { vt = 31 /* VT_LPWSTR */, p = Marshal.StringToCoTaskMemUni(appId) };
            try { Marshal.ThrowExceptionForHR(store.SetValue(ref AppIdKey, ref v)); }
            finally { Marshal.FreeCoTaskMem(v.p); }
            Marshal.ThrowExceptionForHR(store.Commit());
            file.Save(lnkPath, true);
        }
        finally { Marshal.ReleaseComObject(link); }
    }
}
