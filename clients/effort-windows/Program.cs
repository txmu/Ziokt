using System.Diagnostics;
using System.Net.NetworkInformation;
using System.Text.Json;
using Microsoft.Win32;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace ZioktEffort;

internal static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        if (args.Contains("--self-test")) { SelfTest.Run(); return; }
        using var instance = new Mutex(true, @"Local\ZioktEffort-" + Environment.UserName, out bool first);
        if (!first) { MessageBox.Show("Ziokt 助力已在运行，请从系统托盘打开。"); return; }
        Application.Run(new EffortWindow(args.Contains("--background")));
    }
}

internal sealed class Preferences
{
    public string Mode { get; set; } = "network";
    public bool Resume { get; set; }
    internal static string Folder => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ZioktEffort");
    internal static string FileName => Path.Combine(Folder, "preferences.json");
    internal static Preferences Load()
    {
        try { var p = JsonSerializer.Deserialize<Preferences>(File.ReadAllText(FileName)) ?? new(); p.Mode = p.Mode == "compute" ? "compute" : "network"; return p; }
        catch (Exception e) when (e is IOException or JsonException or UnauthorizedAccessException) { return new(); }
    }
    internal void Save()
    {
        Directory.CreateDirectory(Folder);
        string temp = FileName + ".new";
        File.WriteAllText(temp, JsonSerializer.Serialize(this)); File.Move(temp, FileName, true);
    }
}

internal sealed class EffortWindow : Form
{
    const string Origin = "https://fendou.ziokt.com";
    const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    readonly WebView2 web = new() { Dock = DockStyle.Fill };
    readonly Button start = new() { Text = "一键启用（后台继续）", AutoSize = true, Enabled = false };
    readonly Button stop = new() { Text = "停止", AutoSize = true };
    readonly ComboBox mode = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 180 };
    readonly CheckBox startup = new() { Text = "登录时启动并恢复上次助力", AutoSize = true };
    readonly Label state = new() { Text = "正在打开奋斗页…", AutoSize = true, Padding = new Padding(8) };
    readonly NotifyIcon tray = new() { Icon = SystemIcons.Application, Text = "Ziokt 助力 · 可随时停止", Visible = true };
    readonly Preferences prefs = Preferences.Load();
    bool ready, exiting, connected = NetworkInterface.GetIsNetworkAvailable(), navigating;
    readonly bool background;

    internal EffortWindow(bool background)
    {
        this.background = background;
        Text = "Ziokt 助力 · Windows"; Width = 1020; Height = 780; MinimumSize = new Size(540, 480);
        mode.Items.AddRange(["轻量网络协作（主网直连）", "计算协作"]); mode.SelectedIndex = prefs.Mode == "compute" ? 1 : 0;
        var top = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true, Padding = new Padding(8) };
        top.Controls.AddRange([mode, start, stop, startup, state]); Controls.Add(web); Controls.Add(top);
        using (var key = Registry.CurrentUser.OpenSubKey(RunKey)) startup.Checked = key?.GetValue("ZioktEffort") is string;
        startup.CheckedChanged += (_, _) => SetStartup();
        start.Click += async (_, _) => { prefs.Mode = mode.SelectedIndex == 1 ? "compute" : "network"; prefs.Resume = true; Save(); await StartAsync(); };
        stop.Click += async (_, _) => { prefs.Resume = false; Save(); await StopAsync(); state.Text = "已停止；不会自动恢复"; };
        mode.SelectedIndexChanged += async (_, _) => { prefs.Mode = mode.SelectedIndex == 1 ? "compute" : "network"; prefs.Resume = false; Save(); await StopAsync(); };
        var menu = new ContextMenuStrip(); menu.Items.Add("打开奋斗页", null, (_, _) => ShowWindow());
        menu.Items.Add("停止助力", null, async (_, _) => { prefs.Resume = false; Save(); await StopAsync(); });
        menu.Items.Add("退出", null, async (_, _) => { prefs.Resume = false; Save(); await StopAsync(); exiting = true; Close(); });
        tray.ContextMenuStrip = menu; tray.DoubleClick += (_, _) => ShowWindow();
        NetworkChange.NetworkAvailabilityChanged += NetworkChanged;
        FormClosing += (_, e) => { if (e.CloseReason == CloseReason.UserClosing && !exiting) { e.Cancel = true; Hide(); tray.ShowBalloonTip(2500, "Ziokt 助力", "程序仍在托盘运行。右键托盘可停止或退出。", ToolTipIcon.Info); } };
        FormClosed += (_, _) => { NetworkChange.NetworkAvailabilityChanged -= NetworkChanged; tray.Visible = false; tray.Dispose(); web.Dispose(); };
        Shown += async (_, _) => { await InitializeAsync(); if (background && startup.Checked) Hide(); };
    }
    void Save() { try { prefs.Save(); } catch (Exception e) when (e is IOException or UnauthorizedAccessException) { state.Text = "设置保存失败：" + e.Message; } }
    void ShowWindow() { Show(); WindowState = FormWindowState.Normal; Activate(); }
    void SetStartup()
    {
        try
        {
            using var key = Registry.CurrentUser.CreateSubKey(RunKey);
            if (startup.Checked) key.SetValue("ZioktEffort", '"' + Application.ExecutablePath + "\" --background", RegistryValueKind.String);
            else key.DeleteValue("ZioktEffort", false);
        }
        catch (Exception e) when (e is UnauthorizedAccessException or System.Security.SecurityException or IOException)
        { state.Text = "系统未批准自启：" + e.Message; }
    }
    async Task InitializeAsync()
    {
        try
        {
            // Isolated browser profile; never shares the user's existing browser session.
            string profile = Path.Combine(Preferences.Folder, "session-" + Environment.ProcessId);
            var environment = await CoreWebView2Environment.CreateAsync(null, profile);
            await web.EnsureCoreWebView2Async(environment);
            web.CoreWebView2.Settings.AreDevToolsEnabled = false;
            web.CoreWebView2.Settings.IsWebMessageEnabled = false;
            web.CoreWebView2.PermissionRequested += (_, e) => e.State = CoreWebView2PermissionState.Deny;
            web.CoreWebView2.NavigationStarting += (_, e) => { if (!Allowed(e.Uri)) { e.Cancel = true; state.Text = "已阻止离开官方奋斗页"; } else { ready = false; navigating = true; start.Enabled = false; } };
            web.CoreWebView2.NewWindowRequested += (_, e) => { e.Handled = true; if (Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri) && uri.Scheme == "https") Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true }); };
            web.CoreWebView2.DownloadStarting += (_, e) => e.Cancel = true;
            web.CoreWebView2.NavigationCompleted += async (_, e) =>
            {
                navigating = false; ready = e.IsSuccess && Allowed(web.Source?.AbsoluteUri ?? ""); start.Enabled = ready;
                if (!ready) { state.Text = connected ? "页面暂不可用，点击此处重试" : "网络已断开，等待系统网络恢复"; return; }
                await PublishNetworkAsync();
                state.Text = connected ? "就绪 · 两种方式均可选择；可随时停止" : "网络已断开，已暂停";
                // Automatic contribution requires the user's explicit login-start permission plus saved active intent.
                if (prefs.Resume && (background && startup.Checked)) await StartAsync();
            };
            web.CoreWebView2.ProcessFailed += (_, _) => { ready = false; start.Enabled = false; state.Text = "页面进程已停止，点击状态重载"; };
            state.Click += (_, _) => { if (connected && !navigating) web.CoreWebView2.Navigate(Origin + "/"); };
            web.CoreWebView2.Navigate(Origin + "/");
        }
        catch (WebView2RuntimeNotFoundException)
        {
            state.Text = "需要 Microsoft Edge WebView2 Runtime";
            if (MessageBox.Show("此程序需要微软 WebView2 Runtime。是否打开微软官方下载页？", "安装浏览器运行时", MessageBoxButtons.YesNo) == DialogResult.Yes)
                Process.Start(new ProcessStartInfo("https://developer.microsoft.com/microsoft-edge/webview2/") { UseShellExecute = true });
        }
        catch (Exception e) { state.Text = "启动失败：" + e.Message; }
    }
    internal static bool Allowed(string value) => Uri.TryCreate(value, UriKind.Absolute, out var uri) && uri.Scheme == "https" && uri.Host == "fendou.ziokt.com" && uri.Port == 443 && uri.UserInfo == "";
    async Task PublishNetworkAsync()
    {
        if (!ready) return;
        await ScriptAsync("window.ZioktHostNetworkAvailable=" + (connected ? "true" : "false") + ";window.dispatchEvent(new Event('" + (connected ? "online" : "offline") + "'));'network-state-delivered'");
    }
    void NetworkChanged(object? sender, NetworkAvailabilityEventArgs e)
    {
        if (IsDisposed || !IsHandleCreated) return;
        BeginInvoke(new Action(async () =>
        {
            if (connected == e.IsAvailable) return; connected = e.IsAvailable;
            state.Text = connected ? "网络已恢复，继续先前已启用的助力" : "网络已断开，已暂停；等待系统通知";
            await PublishNetworkAsync();
            if (connected && !ready && !navigating) web.CoreWebView2?.Navigate(Origin + "/");
        }));
    }
    async Task<string?> ScriptAsync(string script)
    {
        if (!ready) return null;
        try { return await web.ExecuteScriptAsync(script); }
        catch (Exception e) when (e is InvalidOperationException or System.Runtime.InteropServices.COMException) { state.Text = "页面操作失败，请点击状态重载"; return null; }
    }
    async Task StartAsync()
    {
        if (!ready) { state.Text = "请等待页面加载完成"; return; }
        var result = await ScriptAsync("(()=>{const m=document.getElementById('help-mode'),b=document.getElementById('start'),bg=document.getElementById('background');if(!m||!b||!bg)return 'unavailable';m.value='" + prefs.Mode + "';m.dispatchEvent(new Event('change'));bg.checked=true;bg.dispatchEvent(new Event('change'));b.click();return 'started'})()");
        state.Text = result == "\"started\"" ? (connected ? "已启用 · 实际任务和回执请看页面" : "等待网络恢复；尚未传输或计算") : "页面尚未就绪，请重试";
    }
    Task StopAsync() => ScriptAsync("(()=>{if(window.ZioktCompute)window.ZioktCompute.stop();if(window.ZioktPeopleRelay)window.ZioktPeopleRelay.stop();return 'stopped'})()");
}

internal static class SelfTest
{
    internal static void Run()
    {
        if (!EffortWindow.Allowed("https://fendou.ziokt.com/") || EffortWindow.Allowed("https://fendou.ziokt.com.evil.invalid/") || EffortWindow.Allowed("http://fendou.ziokt.com/") || EffortWindow.Allowed("https://user:pass@fendou.ziokt.com/") || EffortWindow.Allowed("https://fendou.ziokt.com:8443/")) throw new Exception("Navigation boundary failure");
        var p = new Preferences(); if (p.Mode != "network" || p.Resume) throw new Exception("Consent defaults failure");
        File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "self-test.json"), JsonSerializer.Serialize(new { success = true, navigation_boundary = true, no_automatic_contribution_default = true, network_detection = "NetworkAvailabilityChanged", device_test = "not_assessed" }));
    }
}
