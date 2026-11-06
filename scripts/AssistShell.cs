// Windows helpers for the launcher scripts:
//  - read and set a shortcut's AppUserModelID (install-shortcuts.ps1): each shortcut
//    gets its own ID, so Windows shows our icon and pins our shortcut
//  - find, focus and close the app window (assist.ps1)
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

    // ---------- The app window (a Chrome --app window titled "Assist Voice") ----------

    delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc proc, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd, System.Text.StringBuilder s, int max);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr hwnd, System.Text.StringBuilder s, int max);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd, int cmd);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr hwnd, uint msg, IntPtr w, IntPtr l);

    /// <summary>Visible Chrome/Edge windows whose title is exactly `title`. An app window's
    /// title is the page title; a normal tab's window adds " - Google Chrome", so tabs never match.</summary>
    public static IntPtr[] FindAppWindows(string title)
    {
        var found = new System.Collections.Generic.List<IntPtr>();
        EnumWindows((hwnd, l) =>
        {
            if (!IsWindowVisible(hwnd)) return true;
            var cls = new System.Text.StringBuilder(64);
            GetClassName(hwnd, cls, 64);
            if (cls.ToString() != "Chrome_WidgetWin_1") return true;
            var text = new System.Text.StringBuilder(256);
            GetWindowText(hwnd, text, 256);
            if (text.ToString() == title) found.Add(hwnd);
            return true;
        }, IntPtr.Zero);
        return found.ToArray();
    }

    /// <summary>Bring a window to the front (restoring it if minimised).</summary>
    public static void Focus(IntPtr hwnd)
    {
        if (IsIconic(hwnd)) ShowWindow(hwnd, 9 /* SW_RESTORE */);
        SetForegroundWindow(hwnd);
    }

    /// <summary>Ask a window to close, as if its X was clicked.</summary>
    public static void Close(IntPtr hwnd)
    {
        PostMessage(hwnd, 0x0010 /* WM_CLOSE */, IntPtr.Zero, IntPtr.Zero);
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
