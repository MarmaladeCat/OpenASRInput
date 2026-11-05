// Installer-only coordinator. Never call a nested MSI from a custom action.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Xml.Serialization;
#if CUSTOM_ACTION
using Microsoft.Deployment.WindowsInstaller;
#endif

namespace OpenASR.Installation
{
    public class Product
    {
        public string Code, Kind, Name, Version, Sid;
        public int Context;
        public bool HasPortal;
        public string Identity
        {
            get
            {
                return Code + ":" + Context + ":" + Sid;
            }
        }
    }
    public class Setting
    {
        public string Name, Value;
    }
    public class Request
    {
        public string Package, Digest, Kind;
        public bool WantPortal;
        public List<Product> Products = new List<Product>();
        public List<Setting> Settings = new List<Setting>();
    }
    public interface IInstaller
    {
        List<Product> Scan();
        int Remove(Product product, string log);
        int Install(Request request, string log);
    }
    public static class Replacement
    {
        public static readonly Dictionary<string, string> Families = new Dictionary<string, string> {
            {"input", "{d3a801cf-44d0-55e4-b813-f4f15fa12b7f}"},
            {"portal", "{64e55bb5-b8eb-40fa-bc40-089420d7c0a0}"},
            {"bundle", "{638d1b81-3c59-49e1-9e8d-d0a68157c230}"}
        };
        public static List<Product> Conflicts(IEnumerable<Product> products, string kind, bool wantPortal)
        {
            if (!Families.ContainsKey(kind))
                throw new InvalidDataException("Unknown installer kind");
            return products.Where(p => p.Kind == kind ||
                (kind == "input" && p.Kind == "bundle") ||
                (kind == "portal" && p.Kind == "bundle" && p.HasPortal) ||
                (kind == "bundle" && (p.Kind == "input" || (wantPortal && p.Kind == "portal"))))
                .OrderBy(p => p.Context == 4 ? 1 : 0).ThenBy(p => p.Code).ToList();
        }
        public static string Hash(string path)
        {
            using (var stream = File.OpenRead(path))
            using (var hash = SHA256.Create())
                return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "");
        }
        public static string Quote(string value)
        {
            // Windows CommandLineToArgvW escaping, including trailing backslashes.
            var text = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in value)
            {
                if (c == '\\')
                {
                    slashes++;
                    continue;
                }
                text.Append('\\', c == '"' ? slashes * 2 + 1 : slashes);
                slashes = 0;
                text.Append(c);
            }
            text.Append('\\', slashes * 2);
            return text.Append('"').ToString();
        }
        public static void Execute(Request request, IInstaller installer, string directory, Action<string> progress)
        {
            ValidateSettings(request);
            if (!File.Exists(request.Package) || Hash(request.Package) != request.Digest)
                throw new InvalidDataException("安装包已移动或发生变化，未卸载任何程序。请重新打开安装包。");
            var current = Conflicts(installer.Scan(), request.Kind, request.WantPortal);
            if (!Same(current, request.Products))
                throw new InvalidOperationException("已有安装状态已变化，未卸载任何程序。请重新开始安装并确认。");
            foreach (var product in request.Products)
            {
                progress("正在卸载 " + product.Name + " " + product.Version + "（保留全部数据）…");
                int code = installer.Remove(product, Path.Combine(directory, "remove-" + Guid.Parse(product.Code).ToString("N") + ".log"));
                if (code != 0 && code != 3010 && code != 1605 && code != 1614)
                    throw new InvalidOperationException("旧程序卸载未完成（" + code + "），已停止新安装。用户数据保留。日志：" + directory);
                if (installer.Scan().Any(p => p.Identity == product.Identity))
                    throw new InvalidOperationException("旧程序仍有安装登记，已停止新安装。日志：" + directory);
                if (code == 3010)
                    throw new InvalidOperationException("旧程序已卸载，但 Windows 要求先重启。请重启后重新打开安装包，用户数据保留。");
            }
            if (Conflicts(installer.Scan(), request.Kind, request.WantPortal).Count != 0)
                throw new InvalidOperationException("出现新的冲突安装，已停止，未覆盖其他安装。");
            if (Hash(request.Package) != request.Digest)
                throw new InvalidDataException("安装包已发生变化，已停止。用户数据保留，请重新打开可信安装包。");
            progress("旧程序已卸载，正在打开新安装向导。请在向导中完成安装。\n若取消新安装，用户数据仍会保留。");
            int result = installer.Install(request, Path.Combine(directory, "install.log"));
            if (result != 0 && result != 3010)
                throw new InvalidOperationException("新安装未完成（" + result + "）。旧程序可能已卸载，但用户数据保留；请重新运行安装包。日志：" + directory);
        }
        public static void ValidateSettings(Request request)
        {
            var allowed = new HashSet<string> { "INSTALLDIR", "INPUTDATADIR", "PORTALDATADIR", "BUNDLEDATADIR", "ADDLOCAL", "OPENASRINPUT_NO_LAUNCH" };
            if (request.Settings.Any(p => !allowed.Contains(p.Name)))
                throw new InvalidDataException("Unsupported installer property");
            foreach (var setting in request.Settings)
                MsiSetting(setting);
        }
        public static string MsiSetting(Setting setting)
        {
            string value = setting.Value;
            if (setting.Name.EndsWith("DIR"))
            {
                value = Path.GetFullPath(value).TrimEnd('\\');
                if (value.Length == 2 && value[1] == ':')
                    throw new InvalidDataException("程序及数据目录不能是磁盘根目录。");
            }
            return setting.Name + "=" + Quote(value);
        }
        static bool Same(List<Product> a, List<Product> b)
        {
            return a.Select(p => p.Identity + ":" + p.Version).OrderBy(x => x)
                .SequenceEqual(b.Select(p => p.Identity + ":" + p.Version).OrderBy(x => x));
        }
        public static Form Confirmation(Request request)
        {
            var dialog = new Form
            {
                Text = "检测到已有软件",
                Width = 620,
                Height = 420,
                StartPosition = FormStartPosition.CenterScreen,
                FormBorderStyle = FormBorderStyle.FixedDialog,
                MaximizeBox = false,
                MinimizeBox = false
            };
            var summary = new TextBox
            {
                Left = 22,
                Top = 20,
                Width = 560,
                Height = 220,
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Vertical,
                BorderStyle = BorderStyle.None,
                Text = "本机已安装以下软件：\r\n\r\n" + String.Join("\r\n", request.Products.Select(p =>
                    p.Name + "  " + p.Version + (p.Context == 4 ? "（全计算机）" : "（当前用户）"))) +
                    "\r\n\r\n选择“替换升级”后，先卸载以上旧程序，再安装当前包。配置、数据库、Key 和用户数据保留。\r\n" +
                    (request.Products.Any(p => p.Kind == "bundle") ? "注意：旧联合包将整体卸载，其中包含的 Input 和 Portal 都会移除；数据保留。\r\n" : "") +
                    "停止安装不会修改现有程序。新安装失败或取消时，旧程序不会自动恢复，可重新运行安装包。"
            };
            dialog.Controls.Add(summary);
            dialog.Controls.Add(new Label
            {
                Left = 22,
                Top = 250,
                Width = 560,
                Height = 42,
                Text = "确认后当前向导会结束，由替换助手依次执行卸载和新安装。若出现“安装已取消”页面，请关闭该页面。"
            });
            var stop = new Button { Text = "停止当前安装", Left = 300, Top = 315, Width = 125, Height = 34, DialogResult = DialogResult.Cancel };
            var replace = new Button { Text = "替换升级", Left = 440, Top = 315, Width = 125, Height = 34, DialogResult = DialogResult.OK };
            dialog.Controls.Add(stop);
            dialog.Controls.Add(replace);
            dialog.CancelButton = stop;
            dialog.AcceptButton = stop;
            dialog.Shown += delegate
            {
                summary.SelectionLength = 0;
                stop.Focus();
            };
            return dialog;
        }
        public static int Start(Request request)
        {
            Application.EnableVisualStyles();
            using (var dialog = Confirmation(request))
                if (dialog.ShowDialog() != DialogResult.OK)
                    return 1602;
            string directory = Path.Combine(Path.GetTempPath(), "OpenASR-Replacement-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            string executable = Path.Combine(directory, "Replacement.exe");
            File.Copy(Path.Combine(Path.GetDirectoryName(typeof(Replacement).Assembly.Location), "Replacement.exe"), executable);
            string state = Path.Combine(directory, "request.xml");
            using (var output = File.Create(state))
                new XmlSerializer(typeof(Request)).Serialize(output, request);
            Process.Start(new ProcessStartInfo(executable, "--worker " + Quote(state)) { UseShellExecute = false });
            return 1602; // End this MSI before the detached coordinator runs msiexec.
        }
        [STAThread]
        public static int Main(string[] args)
        {
            if (args.Length != 2 || args[0] != "--worker")
                return 87;
            try
            {
                Request request;
                using (var input = File.OpenRead(args[1]))
                    request = (Request)new XmlSerializer(typeof(Request)).Deserialize(input);
                Application.EnableVisualStyles();
                bool finished = false;
                using (var window = new Form { Text = "替换升级", Width = 600, Height = 235, StartPosition = FormStartPosition.CenterScreen, MaximizeBox = false, MinimizeBox = false })
                {
                    var label = new Label { Left = 22, Top = 22, Width = 540, Height = 145, Text = "正在等待旧安装向导结束…" };
                    window.Controls.Add(label);
                    window.FormClosing += delegate (object sender, FormClosingEventArgs e)
                    {
                        e.Cancel = !finished;
                    };
                    window.Shown += delegate
                    {
                        Task.Factory.StartNew(delegate
                        {
                            Thread.Sleep(1500);
                            try
                            {
                                Execute(request, new WindowsInstaller(), Path.GetDirectoryName(args[1]), text => window.Invoke((Action)(() => label.Text = text)));
                                window.Invoke((Action)(() => { finished = true; window.Close(); }));
                            }
                            catch (Exception error)
                            {
                                window.Invoke((Action)(() => { finished = true; MessageBox.Show(window, error.Message, "替换升级未完成", MessageBoxButtons.OK, MessageBoxIcon.Warning); window.Close(); }));
                            }
                        });
                    };
                    Application.Run(window);
                }
                return 0;
            }
            catch (Exception error) { MessageBox.Show(error.Message, "替换升级未完成"); return 1; }
        }
    }
    public class WindowsInstaller : IInstaller
    {
        [DllImport("msi.dll", CharSet = CharSet.Unicode)] static extern uint MsiEnumRelatedProducts(string upgrade, uint reserved, uint index, StringBuilder code);
        [DllImport("msi.dll", CharSet = CharSet.Unicode)] static extern uint MsiGetProductInfoEx(string code, string sid, uint context, string property, StringBuilder value, ref uint size);
        [DllImport("msi.dll", CharSet = CharSet.Unicode)] static extern int MsiQueryFeatureState(string code, string feature);
        static string Info(string code, uint context, string name)
        {
            uint length = 32767;
            var value = new StringBuilder((int)length);
            uint result = MsiGetProductInfoEx(code, null, context, name, value, ref length);
            if (result == 1605)
                return null;
            if (result != 0)
                throw new InvalidOperationException("无法读取已有 MSI 安装（" + result + "），未卸载任何程序。");
            return value.ToString();
        }
        public List<Product> Scan()
        {
            var products = new List<Product>();
            foreach (var family in Replacement.Families)
                for (uint i = 0; ; i++)
                {
                    var code = new StringBuilder(39);
                    uint result = MsiEnumRelatedProducts(family.Value, 0, i, code);
                    if (result == 259)
                        break;
                    if (result != 0)
                        throw new InvalidOperationException("无法枚举已有 MSI 安装（" + result + "）。");
                    foreach (uint context in new uint[] { 4, 2, 1 })
                    {
                        string version = Info(code.ToString(), context, "VersionString");
                        if (version == null)
                            continue;
                        products.Add(new Product
                        {
                            Code = code.ToString(),
                            Kind = family.Key,
                            Version = version,
                            Name = Info(code.ToString(), context, "InstalledProductName"),
                            Context = (int)context,
                            Sid = context == 4 ? "" : System.Security.Principal.WindowsIdentity.GetCurrent().User.Value,
                            HasPortal = family.Key == "portal" || (family.Key == "bundle" && MsiQueryFeatureState(code.ToString(), "Portal") >= 3)
                        });
                    }
                }
            if (products.GroupBy(p => p.Code).Any(group => group.Count() > 1))
                throw new InvalidOperationException("检测到同一产品存在多个用户/系统安装上下文，请先通过系统卸载入口处理，未修改安装。");
            return products;
        }
        static int Run(string arguments, bool elevated, bool retry)
        {
            for (int attempt = 0; ; attempt++)
            {
                var start = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "msiexec.exe"), arguments) { UseShellExecute = true };
                if (elevated)
                    start.Verb = "runas";
                using (var process = Process.Start(start))
                {
                    process.WaitForExit();
                    if (!retry || process.ExitCode != 1618 || attempt >= 29)
                        return process.ExitCode;
                }
                Thread.Sleep(2000);
            }
        }
        public int Remove(Product product, string log)
        {
            Guid.Parse(product.Code);
            return Run("/x " + product.Code + " /qn /norestart REMOVEUSERDATA=0 /l*v " + Replacement.Quote(log), product.Context == 4, true);
        }
        public int Install(Request request, string log)
        {
            Replacement.ValidateSettings(request);
            return Run("/i " + Replacement.Quote(request.Package) + " /norestart REMOVEUSERDATA=0 /l*v " + Replacement.Quote(log) + " " +
                String.Join(" ", request.Settings.Select(Replacement.MsiSetting)), false, true);
        }
    }
#if CUSTOM_ACTION
    public static class ReplacementActions {
        static Request Read(Session session) {
            string kind = session["OPENASR_INSTALLER_KIND"];
            bool portal = kind == "portal" || (kind == "bundle" && session.EvaluateCondition("&Portal=3"));
            var request = new Request { Package = session["OriginalDatabase"], Kind = kind, WantPortal = portal };
            var inventory = new WindowsInstaller().Scan();
            if (portal && !inventory.Any(p => p.Kind == "portal" || (p.Kind == "bundle" && p.HasPortal)))
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\OpenASRPortal"))
                    if (key != null) throw new InvalidOperationException("检测到未由已知 MSI 管理的 Portal 服务。为保护现有程序，未卸载任何软件；请先处理旧服务或取消安装 Portal。");
            request.Products = Replacement.Conflicts(inventory, kind, portal);
            return request;
        }
        static void PreserveData(Session session, Request request) {
            foreach (var product in request.Products) {
                using (var hive = Microsoft.Win32.RegistryKey.OpenBaseKey(product.Kind == "input" ? Microsoft.Win32.RegistryHive.CurrentUser : Microsoft.Win32.RegistryHive.LocalMachine, Microsoft.Win32.RegistryView.Registry64))
                using (var key = hive.OpenSubKey(@"Software\" + (product.Kind == "input" ? "OpenASRInput" : product.Kind == "portal" ? "OpenASRPortal" : "OpenASRInputPortal"))) {
                    if (key == null) continue;
                    foreach (var pair in new[] {new[]{"INPUTDATADIR", product.Kind == "bundle" ? "InputStateDir" : "StateDir"}, new[]{"PORTALDATADIR", product.Kind == "bundle" ? "PortalStateDir" : "StateDir"}}) {
                        if ((pair[0] == "INPUTDATADIR" && product.Kind == "portal") || (pair[0] == "PORTALDATADIR" && (product.Kind == "input" || !request.WantPortal))) continue;
                        string path = key.GetValue(pair[1]) as string;
                        if (String.IsNullOrEmpty(path)) continue;
                        var setting = request.Settings.FirstOrDefault(p => p.Name == pair[0]);
                        string defaultPath = Path.Combine(Environment.GetFolderPath(pair[0] == "INPUTDATADIR" ? Environment.SpecialFolder.ApplicationData : Environment.SpecialFolder.CommonApplicationData), pair[0] == "INPUTDATADIR" ? "OpenASRInput" : "OpenASRPortal");
                        if (setting != null && !String.Equals(Path.GetFullPath(setting.Value).TrimEnd('\\'), defaultPath, StringComparison.OrdinalIgnoreCase)) continue;
                        if (setting == null) request.Settings.Add(new Setting { Name = pair[0], Value = path }); else setting.Value = path;
                    }
                }
            }
        }
        [CustomAction] public static ActionResult ConfirmReplacement(Session session) {
            try {
                var request = Read(session);
                if (request.Products.Count == 0) return ActionResult.Success;
                request.Digest = Replacement.Hash(request.Package);
                foreach (string name in new[] { "INSTALLDIR", "INPUTDATADIR", "PORTALDATADIR", "BUNDLEDATADIR", "OPENASRINPUT_NO_LAUNCH" })
                    if (!String.IsNullOrEmpty(session[name])) request.Settings.Add(new Setting { Name = name, Value = session[name] });
                if (request.Kind == "bundle") request.Settings.Add(new Setting { Name = "ADDLOCAL", Value = request.WantPortal ? "InputCore,Portal" : "InputCore" });
                PreserveData(session, request);
                Replacement.Start(request);
                return ActionResult.UserExit;
            } catch (Exception error) {
                session.Log("Replacement preflight failed: " + error.Message);
                MessageBox.Show(error.Message, "无法开始替换升级", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return ActionResult.Failure;
            }
        }
        [CustomAction] public static ActionResult GuardReplacement(Session session) {
            try {
                if (Read(session).Products.Count == 0) return ActionResult.Success;
                using (var record = new Record(1)) {
                    record[0] = "检测到已有软件。请完整打开安装向导，选择“替换升级”或停止安装；静默安装不会自动卸载旧程序。";
                    session.Message(InstallMessage.Error, record);
                }
                return ActionResult.Failure;
            } catch (Exception error) { session.Log("Replacement guard failed: " + error.Message); return ActionResult.Failure; }
        }
    }
#endif
}
