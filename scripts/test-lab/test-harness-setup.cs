// Inspect the real form and bridge in an isolated test cache, without a CLI model call.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class HarnessSetupProbe {
    private const BindingFlags Members = BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static;
    private static void CaptureFonts(Control control, Dictionary<Control, Font> fonts) {
        fonts.Add(control, control.Font);
        foreach (Control child in control.Controls) CaptureFonts(child, fonts);
    }
    private static void StressScale(Form form, float scale, bool compact) {
        var fonts = new Dictionary<Control, Font>(); CaptureFonts(form, fonts);
        form.AutoScaleMode = AutoScaleMode.None;
        form.Scale(new SizeF(scale, scale));
        foreach (var item in fonts) item.Key.Font = new Font(item.Value.FontFamily, item.Value.SizeInPoints * scale, item.Value.Style);
        if (compact) { form.MinimumSize = Size.Empty; form.ClientSize = new Size(660, 415); }
        form.PerformLayout(); Application.DoEvents();
    }
    private static object Box(Form form, Control control) {
        Point p = form.PointToClient(control.Parent.PointToScreen(control.Location));
        Size preferred = control.GetPreferredSize(new Size(control.Width, 0));
        return new Dictionary<string, object> {
            { "x", p.X }, { "y", p.Y }, { "width", control.Width }, { "height", control.Height },
            { "preferredHeight", preferred.Height }, { "visible", control.Visible }, { "fontPoints", control.Font.SizeInPoints }
        };
    }
    [STAThread]
    private static int Main(string[] args) {
        try {
            Assembly assembly = Assembly.LoadFile(Path.GetFullPath(args[0]));
            Type payload = assembly.GetType("CompanyAgent.Setup.Payload", true);
            var json = new JavaScriptSerializer();
            if (args[1] == "prepare-only") {
                string root = (string)payload.GetMethod("Prepare", Members).Invoke(null, new object[] { args[2] });
                File.WriteAllText(args[3], json.Serialize(new Dictionary<string, object> {
                    { "status", "prepared" }, { "root", root }
                }));
                return 0;
            }
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            if (args[1] == "run") {
                string root = (string)payload.GetMethod("Prepare", Members).Invoke(null, new object[] { args[2] });
                var request = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(args[4]));
                object result = payload.GetMethod("Run", Members).Invoke(null, new object[] { root, request, new Action<string>(delegate(string s) { }) });
                File.WriteAllText(args[3], json.Serialize(result)); return 0;
            }
            Type formType = assembly.GetType("CompanyAgent.Setup.SetupForm", true);
            using (Form form = (Form)Activator.CreateInstance(formType, Members, null, new object[] { args[2] }, null)) {
                form.StartPosition = FormStartPosition.Manual; form.Location = new Point(-32000, -32000); form.ShowInTaskbar = false;
                form.Show(); Application.DoEvents();
                // Production Application.Run owns this context; the probe uses
                // a bounded manual message pump instead of a persistent loop.
                SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
                if (args[1] == "render") {
                    if (args.Length > 4) StressScale(form, Single.Parse(args[4], System.Globalization.CultureInfo.InvariantCulture), args.Length > 5 && args[5] == "compact");
                    using (var bitmap = new Bitmap(form.Width, form.Height)) { form.DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size)); bitmap.Save(args[3]); }
                    return 0;
                }
                if (args[1] == "layout") {
                    if (args.Length > 4) StressScale(form, Single.Parse(args[4], System.Globalization.CultureInfo.InvariantCulture), args.Length > 5 && args[5] == "compact");
                    var layoutReport = new Dictionary<string, object> { { "width", form.ClientSize.Width }, { "height", form.ClientSize.Height }, { "dpi", form.DeviceDpi }, { "title", form.Text }, { "headingText", ((Label)formType.GetField("heading", Members).GetValue(form)).Text } };
                    foreach (string name in new[] { "heading", "introduction", "user", "project", "folder", "browse", "status", "install", "close" }) {
                        Control control = (Control)formType.GetField(name, Members).GetValue(form);
                        layoutReport[name] = Box(form, control);
                    }
                    layoutReport["scrollable"] = ((Panel)formType.GetField("body", Members).GetValue(form)).VerticalScroll.Visible;
                    File.WriteAllText(args[3], json.Serialize(layoutReport)); return 0;
                }
                if (args.Length > 4) {
                    ((RadioButton)formType.GetField("project", Members).GetValue(form)).Checked = true;
                    ((TextBox)formType.GetField("folder", Members).GetValue(form)).Text = args[4];
                }
                var install = (Button)formType.GetField("install", Members).GetValue(form);
                var close = (Button)formType.GetField("close", Members).GetValue(form);
                install.PerformClick();
                bool busyAtStart = (bool)formType.GetField("busy", Members).GetValue(form);
                bool closeDisabled = !close.Enabled;
                DateTime deadline = DateTime.UtcNow.AddSeconds(30);
                while ((bool)formType.GetField("busy", Members).GetValue(form)) {
                    if (DateTime.UtcNow > deadline) throw new TimeoutException("Installer fixture timed out.");
                    Application.DoEvents(); Thread.Sleep(10);
                }
                var report = new Dictionary<string, object> {
                    { "message", ((Label)formType.GetField("status", Members).GetValue(form)).Text },
                    { "installVisible", install.Visible }, { "closeEnabled", close.Enabled },
                    { "busyAtStart", busyAtStart }, { "closeDisabledDuringWork", closeDisabled },
                    { "details", ((TextBox)formType.GetField("diagnostic", Members).GetValue(form)).Text }
                };
                File.WriteAllText(args[3], json.Serialize(report));
            }
            return 0;
        } catch (Exception error) { Console.Error.WriteLine(error.ToString()); return 1; }
    }
}
