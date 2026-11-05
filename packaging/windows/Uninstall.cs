using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class Uninstall
{
    [DllImport("msi.dll", CharSet = CharSet.Unicode)]
    static extern uint MsiGetProductInfo(string product, string property, StringBuilder value, ref uint size);
    [DllImport("msi.dll", CharSet = CharSet.Unicode)]
    static extern int MsiQueryFeatureState(string product, string feature);

    static string InstallDirectory(string code)
    {
        uint size = 32767;
        var value = new StringBuilder((int)size);
        uint error = MsiGetProductInfo(code, "InstallLocation", value, ref size);
        if (error != 0 || String.IsNullOrWhiteSpace(value.ToString()))
            throw new InvalidOperationException("无法确认已安装程序的位置，未停止任何服务。Windows Installer: " + error);
        return Path.GetFullPath(value.ToString()).TrimEnd('\\');
    }

    internal static bool OwnsService(string image, string expected)
    {
        if (String.IsNullOrWhiteSpace(image))
            return false;
        string path = Environment.ExpandEnvironmentVariables(image).Trim();
        if (path.StartsWith("\""))
        {
            int end = path.IndexOf('"', 1);
            if (end < 0 || path.Substring(end + 1).Trim().Length != 0)
                return false;
            path = path.Substring(1, end - 1);
        }
        try
        {
            return String.Equals(Path.GetFullPath(path), Path.GetFullPath(expected), StringComparison.OrdinalIgnoreCase);
        }
        catch (ArgumentException) { return false; }
    }

    static void StopPortal(string directory)
    {
        using (var registry = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64))
        using (var key = registry.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\OpenASRPortal"))
        {
            if (key == null)
                return;
            if (!OwnsService(key.GetValue("ImagePath") as string, Path.Combine(directory, "OpenASRPortal.exe")))
                throw new InvalidOperationException("Portal 服务属于其他安装，已停止卸载；没有关闭服务或删除数据。");
        }
        using (var service = new ServiceController("OpenASRPortal"))
        {
            service.Refresh();
            if (service.Status == ServiceControllerStatus.Stopped)
                return;
            if (service.Status == ServiceControllerStatus.StartPending)
                service.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(60));
            service.Refresh();
            if (service.Status != ServiceControllerStatus.StopPending)
                service.Stop();
            service.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(60));
        }
    }

    static void StopInput(string directory)
    {
        string launcher = Path.Combine(directory, "OpenASRInput.exe");
        if (!File.Exists(launcher))
            return; // MSI also carries a shutdown launcher for missing files.
        using (var process = Process.Start(new ProcessStartInfo(launcher, "--shutdown \"" + directory + "\\.\"")
        {
            UseShellExecute = false,
            CreateNoWindow = true
        }))
        {
            if (!process.WaitForExit(20000) || process.ExitCode != 0)
                throw new InvalidOperationException("输入法尚未退出，已停止卸载，请稍后重试。");
        }
    }

    [STAThread]
    static int Main(string[] args)
    {
        bool quiet = args.Contains("--quiet");
        try
        {
            string directory = AppDomain.CurrentDomain.BaseDirectory;
            string[] lines = File.ReadAllLines(Path.Combine(directory, "uninstall.ini"));
            string name = lines[0], code = lines[1];
            Guid.Parse(code);
            bool bundle = name == "OpenASRInput + Portal", machine = bundle || name == "OpenASRPortal";
            if (!bundle && !machine && name != "OpenASRInput")
                throw new InvalidOperationException("未知的卸载产品。");
            if (!args.Contains("--worker"))
            {
                string temp = Path.Combine(Path.GetTempPath(), "OpenASR-Uninstall-" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(temp);
                string target = Path.Combine(temp, "Uninstall.exe");
                File.Copy(Application.ExecutablePath, target);
                File.Copy(Path.Combine(directory, "uninstall.ini"), Path.Combine(temp, "uninstall.ini"));
                Process.Start(new ProcessStartInfo(target, "--worker" + (quiet ? " --quiet" : "") + (args.Contains("--remove-data") ? " --remove-data" : "")) { UseShellExecute = true });
                return 0;
            }
            bool wipe = args.Contains("--remove-data");
            if (!quiet && !args.Contains("--confirmed"))
            {
                Application.EnableVisualStyles();
                using (var dialog = new Form
                {
                    Text = "卸载 " + name,
                    Width = 550,
                    Height = 285,
                    StartPosition = FormStartPosition.CenterScreen,
                    FormBorderStyle = FormBorderStyle.FixedDialog,
                    MaximizeBox = false,
                    MinimizeBox = false
                })
                {
                    dialog.Controls.Add(new Label
                    {
                        Left = 24,
                        Top = 22,
                        Width = 490,
                        Height = 65,
                        Text = "卸载前会自动关闭输入法，并停止本次安装的 Portal 服务。\n请选择是否保留配置文件。"
                    });
                    var keep = new CheckBox
                    {
                        Name = "KeepConfiguration",
                        AccessibleName = "保留配置文件",
                        Left = 24,
                        Top = 92,
                        Width = 490,
                        Height = 28,
                        Text = "保留配置文件（下次安装可继续使用）",
                        Checked = true
                    };
                    dialog.Controls.Add(keep);
                    dialog.Controls.Add(new Label
                    {
                        Left = 24,
                        Top = 125,
                        Width = 490,
                        Height = 48,
                        Text = "取消勾选将删除" + (machine ? "本包管理的所有用户" : "当前用户") + "的配置、Key、数据库、缓存、备份和日志。"
                    });
                    var cancel = new Button { Text = "取消", Left = 300, Top = 190, Width = 90, DialogResult = DialogResult.Cancel };
                    var confirm = new Button { Text = "卸载", Left = 400, Top = 190, Width = 100 };
                    confirm.Click += delegate
                    {
                        if (!keep.Checked && MessageBox.Show("确定删除本产品的全部配置和数据？此操作无法恢复。", name,
                            MessageBoxButtons.YesNo, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) != DialogResult.Yes)
                            return;
                        wipe = !keep.Checked;
                        dialog.DialogResult = DialogResult.OK;
                        dialog.Close();
                    };
                    dialog.Controls.Add(cancel);
                    dialog.Controls.Add(confirm);
                    dialog.CancelButton = cancel;
                    if (dialog.ShowDialog() != DialogResult.OK)
                        return 0;
                }
            }
            if (machine && !new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator))
            {
                using (var elevated = Process.Start(new ProcessStartInfo(Application.ExecutablePath,
                    "--worker --confirmed" + (quiet ? " --quiet" : "") + (wipe ? " --remove-data" : ""))
                {
                    UseShellExecute = true,
                    Verb = "runas"
                }))
                {
                    elevated.WaitForExit();
                    return elevated.ExitCode;
                }
            }
            string install = InstallDirectory(code);
            if (bundle || !machine)
                StopInput(bundle ? Path.Combine(install, "Input") : install);
            if (machine && (!bundle || MsiQueryFeatureState(code, "Portal") == 3))
                StopPortal(bundle ? Path.Combine(install, "Portal") : install);
            string log = Path.Combine(directory, "uninstall.log");
            string command = "/x " + code + " REMOVEUSERDATA=" + (wipe ? "1" : "0") + " /norestart /l*v \"" + log + "\"" + (quiet ? " /qn" : " /qb");
            using (var process = Process.Start(new ProcessStartInfo("msiexec.exe", command) { UseShellExecute = true }))
            {
                process.WaitForExit();
                if (!quiet && process.ExitCode != 0 && process.ExitCode != 3010)
                    MessageBox.Show("卸载失败，Windows Installer 返回 " + process.ExitCode + "。\n日志：" + log, "卸载", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return process.ExitCode;
            }
        }
        catch (System.ComponentModel.Win32Exception error)
        {
            if (error.NativeErrorCode == 1223)
                return 1602; // UAC cancelled, no stop or deletion.
            if (!quiet)
                MessageBox.Show(error.Message, "卸载失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        catch (Exception error)
        {
            if (!quiet)
                MessageBox.Show(error.Message, "卸载失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
