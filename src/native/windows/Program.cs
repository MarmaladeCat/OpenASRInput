using System.IO;
using System.Text;
using Forms = System.Windows.Forms;

namespace OpenASRInput;

internal static class Program
{
    private static readonly object OutputLock = new();
    internal static void Send(string line)
    {
        lock (OutputLock)
        {
            Console.WriteLine(line);
            Console.Out.Flush();
        }
    }
    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            // A WinExe started with CREATE_NO_WINDOW has pipes, but no console.
            // Console.OutputEncoding/InputEncoding call console APIs on Windows
            // and can fail with ERROR_INVALID_HANDLE before the handshake.
            var utf8 = new UTF8Encoding(false, true);
            Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), utf8) { AutoFlush = true });
            Console.SetError(new StreamWriter(Console.OpenStandardError(), utf8) { AutoFlush = true });
            Console.SetIn(new StreamReader(Console.OpenStandardInput(), utf8));
            if (args.FirstOrDefault() == "--devices")
            {
                Capture.Devices();
                return 0;
            }
            if (args.FirstOrDefault() == "--capture")
            {
                Capture.Run(args.ElementAtOrDefault(1) ?? "default");
                return 0;
            }
            Forms.Application.SetHighDpiMode(Forms.HighDpiMode.PerMonitorV2);
            Forms.Application.EnableVisualStyles();
            using var host = new Host();
            _ = Task.Run(async () =>
            {
                try
                {
                    while (await Console.In.ReadLineAsync() is string line)
                    {
                        var answer = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
                        host.BeginInvoke(() => answer.SetResult(host.Request(line)));
                        Send(await answer.Task);
                    }
                }
                finally { if (!host.IsDisposed) host.BeginInvoke(() => Forms.Application.Exit()); }
            });
            Forms.Application.Run(host);
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; }
    }
}
