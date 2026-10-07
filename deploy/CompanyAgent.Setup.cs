// Single-file, same-user setup UI around the existing installer.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace CompanyAgent.Setup {
    internal static class Program {
        [STAThread]
        private static int Main(string[] args) {
            bool quiet = args.Length > 0;
            try {
                if (args.Length > 0) {
                    if (args[0] != "--verify-only" || (args.Length != 1 && args.Length != 3) ||
                        (args.Length == 3 && args[1] != "--cache-root")) return 2;
                    Payload.Prepare(args.Length == 3 ? args[2] : null);
                    return 0;
                }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new SetupForm());
                return 0;
            } catch (Exception error) {
                if (!quiet) MessageBox.Show("설치 화면을 열지 못했습니다.\n\n" + error.Message,
                    "Company Harness 설치", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
    }

    internal static class Payload {
        internal static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 };
        internal static Stream Resource(string name) {
            Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name);
            if (stream == null) throw new InvalidDataException("설치 파일이 완전하지 않습니다. 다시 내려받아 주세요.");
            return stream;
        }
        internal static string ResourceText(string name) {
            using (Stream stream = Resource(name))
            using (StreamReader reader = new StreamReader(stream, new UTF8Encoding(false, true))) return reader.ReadToEnd();
        }
        internal static string Hash(Stream stream) {
            using (SHA256 sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }
        internal static string Relative(string value) {
            if (String.IsNullOrEmpty(value) || value.IndexOf('\\') >= 0 || value.StartsWith("/")) throw new InvalidDataException("설치 파일 경로가 올바르지 않습니다.");
            foreach (string part in value.Split('/'))
                if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(".") || part.EndsWith(" ") ||
                    part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || Regex.IsMatch(part, @"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", RegexOptions.IgnoreCase))
                    throw new InvalidDataException("설치 파일 경로가 올바르지 않습니다.");
            return value;
        }
        private static void NoLinks(string path) {
            string current = Path.GetFullPath(path);
            while (!String.IsNullOrEmpty(current)) {
                if ((Directory.Exists(current) || File.Exists(current)) &&
                    (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("설치 준비 폴더가 다른 위치로 연결되어 있습니다. 담당자에게 확인해 주세요.");
                current = Path.GetDirectoryName(current);
            }
        }
        private static void Verify(string target, Dictionary<string, string> manifest, string bridgeHash) {
            foreach (var item in manifest) {
                string file = Path.Combine(target, "bundle", item.Key.Replace('/', Path.DirectorySeparatorChar));
                NoLinks(file);
                using (var stream = File.OpenRead(file)) if (Hash(stream) != item.Value) throw new InvalidDataException("설치 파일 검증에 실패했습니다. 다시 내려받아 주세요.");
            }
            string bridge = Path.Combine(target, "SetupBridge.ps1");
            NoLinks(bridge);
            using (var stream = File.OpenRead(bridge)) if (Hash(stream) != bridgeHash) throw new InvalidDataException("설치 연결 파일을 확인할 수 없습니다.");
            var directories = new Stack<string>(); directories.Push(Path.Combine(target, "bundle"));
            while (directories.Count > 0) {
                string directory = directories.Pop(); NoLinks(directory);
                foreach (string file in Directory.GetFileSystemEntries(directory)) {
                    NoLinks(file);
                    if (Directory.Exists(file)) { directories.Push(file); continue; }
                    string name = file.Substring(Path.Combine(target, "bundle").Length + 1).Replace('\\', '/');
                    if (!manifest.ContainsKey(name)) throw new InvalidDataException("설치 폴더에 다른 파일이 있습니다. 담당자에게 확인해 주세요.");
                }
            }
        }
        internal static string Prepare(string cacheRoot) {
            string[] build = ResourceText("SetupBuild.txt").Trim().Split('\n');
            if (build.Length != 3 || !Regex.IsMatch(build[0].Trim(), @"^\d+\.\d+\.\d+$") ||
                !Regex.IsMatch(build[1].Trim(), "^[0-9a-f]{64}$") || !Regex.IsMatch(build[2].Trim(), "^[0-9a-f]{64}$")) throw new InvalidDataException("설치 파일 정보를 읽지 못했습니다.");
            string version = build[0].Trim(), zipHash = build[1].Trim(), bridgeHash = build[2].Trim();
            var manifest = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (string row in ResourceText("SetupPayload.manifest.tsv").Split('\n')) {
                if (String.IsNullOrWhiteSpace(row)) continue;
                string[] fields = row.TrimEnd('\r').Split('\t');
                if (fields.Length != 2 || !Regex.IsMatch(fields[0], "^[0-9a-f]{64}$")) throw new InvalidDataException("설치 파일 목록을 읽지 못했습니다.");
                manifest.Add(Relative(fields[1]), fields[0]);
            }
            if (!manifest.ContainsKey("bundle-manifest.json") || !manifest.ContainsKey("deploy/Setup-CompanyAgent.ps1") || manifest.Count > 5000) throw new InvalidDataException("직원 설치 파일이 아닙니다.");
            cacheRoot = Path.GetFullPath(cacheRoot ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CompanyAgent", "setup-cache"));
            NoLinks(cacheRoot);
            string target = Path.Combine(cacheRoot, version + "-" + zipHash.Substring(0, 16) + "-" + bridgeHash.Substring(0, 8));
            using (var mutex = new Mutex(false, @"Local\CompanyAgentSetup-" + WindowsIdentity.GetCurrent().User.Value + "-" + zipHash)) {
                bool held = false;
                try {
                    try { held = mutex.WaitOne(TimeSpan.FromSeconds(30)); } catch (AbandonedMutexException) { held = true; }
                    if (!held) throw new IOException("다른 설치 창에서 준비 중입니다. 잠시 후 다시 실행해 주세요.");
                    NoLinks(target);
                    if (!Directory.Exists(target)) {
                        Directory.CreateDirectory(cacheRoot);
                        string staging = Path.Combine(cacheRoot, ".prepare-" + Guid.NewGuid().ToString("N"));
                        Directory.CreateDirectory(Path.Combine(staging, "bundle"));
                        using (Stream resource = Resource("SetupPayload.zip")) {
                            if (Hash(resource) != zipHash) throw new InvalidDataException("설치 파일이 손상됐습니다. 다시 내려받아 주세요.");
                            resource.Position = 0;
                            using (var archive = new ZipArchive(resource, ZipArchiveMode.Read, false)) {
                                var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                                long total = 0;
                                foreach (var entry in archive.Entries) {
                                    string name = entry.FullName.Replace('\\', '/');
                                    if (name.EndsWith("/")) { Relative(name.TrimEnd('/')); continue; }
                                    name = Relative(name);
                                    total += entry.Length;
                                    if (!seen.Add(name) || !manifest.ContainsKey(name) || entry.Length > 256L * 1024 * 1024 || total > 512L * 1024 * 1024 ||
                                        ((entry.ExternalAttributes >> 16) & 61440) == 40960) throw new InvalidDataException("설치 파일 구성이 올바르지 않습니다.");
                                    string file = Path.Combine(staging, "bundle", name.Replace('/', Path.DirectorySeparatorChar));
                                    Directory.CreateDirectory(Path.GetDirectoryName(file));
                                    using (Stream input = entry.Open()) using (Stream output = File.Open(file, FileMode.CreateNew, FileAccess.Write)) input.CopyTo(output);
                                }
                                if (seen.Count != manifest.Count) throw new InvalidDataException("설치 파일 일부가 없습니다.");
                            }
                        }
                        using (Stream input = Resource("SetupBridge.ps1")) using (Stream output = File.Open(Path.Combine(staging, "SetupBridge.ps1"), FileMode.CreateNew, FileAccess.Write)) input.CopyTo(output);
                        Verify(staging, manifest, bridgeHash);
                        NoLinks(target);
                        Directory.Move(staging, target);
                    }
                    Verify(target, manifest, bridgeHash);
                    return target;
                } finally { if (held) mutex.ReleaseMutex(); }
            }
        }
        internal static string Quote(string value) {
            var text = new StringBuilder("\""); int slashes = 0;
            foreach (char c in value) {
                if (c == '\\') { slashes++; continue; }
                text.Append('\\', slashes * (c == '"' ? 2 : 1) + (c == '"' ? 1 : 0)); text.Append(c); slashes = 0;
            }
            return text.Append('\\', slashes * 2).Append('"').ToString();
        }
        internal static Dictionary<string, object> Run(string root, Dictionary<string, object> request, Action<string> progress) {
            string job = Path.Combine(root, "requests", Guid.NewGuid().ToString("N"));
            NoLinks(job); Directory.CreateDirectory(job);
            string input = Path.Combine(job, "request.json"), output = Path.Combine(job, "result.json");
            File.WriteAllText(input, Json.Serialize(request), new UTF8Encoding(false));
            try {
                string system = Environment.GetFolderPath(Environment.SpecialFolder.System);
                string ps = Path.Combine(system, @"WindowsPowerShell\v1.0\powershell.exe");
                var start = new ProcessStartInfo(ps, "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + Quote(Path.Combine(root, "SetupBridge.ps1")) + " -BundleRoot " + Quote(Path.Combine(root, "bundle")) + " -RequestFile " + Quote(input) + " -ResultFile " + Quote(output));
                start.UseShellExecute = false; start.CreateNoWindow = true;
                start.RedirectStandardOutput = true; start.RedirectStandardError = true;
                start.StandardOutputEncoding = Encoding.UTF8; start.StandardErrorEncoding = Encoding.UTF8;
                start.WorkingDirectory = Path.Combine(root, "bundle");
                // Child-only module path avoids importing PowerShell 7 modules into 5.1.
                start.EnvironmentVariables["PSModulePath"] = Path.Combine(system, @"WindowsPowerShell\v1.0\Modules");
                var errors = new StringBuilder();
                using (var process = new Process { StartInfo = start }) {
                    process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) {
                        if (e.Data != null && Regex.IsMatch(e.Data, @"^\[[1-4]/4\]")) progress(e.Data.Substring(5).Trim());
                    };
                    process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { lock(errors) if (e.Data != null && errors.Length < 16000) errors.AppendLine(e.Data); };
                    process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine(); process.WaitForExit();
                    if (!File.Exists(output)) throw new IOException("설치 프로그램이 결과를 전달하지 못했습니다.\n" + errors.ToString());
                    if (new FileInfo(output).Length > 4 * 1024 * 1024) throw new InvalidDataException("설치 결과가 너무 큽니다.");
                    var result = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(output, Encoding.UTF8));
                    string status = Get(result, "status");
                    if (process.ExitCode != 0 && status != "failed") throw new IOException("설치 프로그램이 정상 종료되지 않았습니다.");
                    return result;
                }
            } finally {
                if (File.Exists(input)) File.Delete(input);
                if (File.Exists(output)) File.Delete(output);
                Directory.Delete(job, false);
            }
        }
        internal static string Get(Dictionary<string, object> value, string key) { object item; return value.TryGetValue(key, out item) && item != null ? Convert.ToString(item) : ""; }
    }

    internal sealed class SetupForm : Form {
        private readonly RadioButton user = new RadioButton { Text = "내 Claude Code 전체에서 사용", Checked = true, AutoSize = true };
        private readonly RadioButton project = new RadioButton { Text = "선택한 업무 폴더에서만 사용", AutoSize = true };
        private readonly TextBox folder = new TextBox { ReadOnly = true, Dock = DockStyle.Fill, Enabled = false };
        private readonly Button browse = new Button { Text = "폴더 선택", AutoSize = true, Enabled = false };
        private readonly Button install = new Button { Text = "설치하기", AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, MinimumSize = new Size(120, 38), Padding = new Padding(14, 6, 14, 6), FlatStyle = FlatStyle.Flat };
        private readonly Button close = new Button { Text = "닫기", AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, MinimumSize = new Size(85, 38), Padding = new Padding(12, 6, 12, 6) };
        private readonly Label status = new Label { Text = "사용할 범위를 고르고 설치하기를 눌러 주세요.", AutoSize = true, MaximumSize = new Size(600, 0) };
        private readonly ProgressBar progress = new ProgressBar { Dock = DockStyle.Fill, Style = ProgressBarStyle.Marquee, Visible = false };
        private readonly LinkLabel details = new LinkLabel { Text = "자세히 보기", AutoSize = true, Visible = false };
        private readonly LinkLabel guide = new LinkLabel { Text = "사용 안내서 열기", AutoSize = true, Visible = false };
        private readonly TextBox diagnostic = new TextBox { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, Visible = false };
        private bool busy;
        private string payloadRoot;
        private readonly string cacheRoot;
        private readonly TableLayoutPanel content = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, ColumnCount = 1 };
        private readonly Panel body = new Panel { Dock = DockStyle.Fill, AutoScroll = true, Margin = Padding.Empty };
        private readonly Label heading = new Label { Text = "Company Harness", AutoSize = true, Dock = DockStyle.Top, ForeColor = Color.FromArgb(29, 56, 82) };
        private readonly Label introduction = new Label { Text = "기존 Claude Code에 회사 업무 기능을 추가합니다.\n로그인·모델 설정과 개인 자료는 이어서 사용합니다.", AutoSize = true, Dock = DockStyle.Top };
        private bool updatingWidths;

        internal SetupForm() : this(null) { }
        internal SetupForm(string cacheRoot) {
            this.cacheRoot = cacheRoot;
            SuspendLayout();
            AutoScaleDimensions = new SizeF(96F, 96F);
            AutoScaleMode = AutoScaleMode.Dpi;
            Text = "Company Harness 설치"; ClientSize = new Size(660, 415);
            MinimumSize = new Size(560, 360); StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("맑은 고딕", 10F); BackColor = Color.FromArgb(247, 249, 252);
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(26), ColumnCount = 1, RowCount = 2 };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            content.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            heading.Font = new Font(Font.FontFamily, 21F, FontStyle.Bold);
            heading.Margin = new Padding(0, 0, 0, 12); introduction.Margin = new Padding(0, 0, 0, 18);
            user.Margin = new Padding(0, 0, 0, 10); project.Margin = new Padding(0, 0, 0, 12);
            user.Dock = DockStyle.Top; project.Dock = DockStyle.Top;
            var folders = new TableLayoutPanel { ColumnCount = 2, Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Margin = new Padding(0, 0, 0, 12) };
            folders.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); folders.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            folder.Anchor = AnchorStyles.Left | AnchorStyles.Right;
            browse.Padding = new Padding(10, 4, 10, 4); browse.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            folders.Controls.Add(folder, 0, 0); folders.Controls.Add(browse, 1, 0);
            status.Dock = DockStyle.Top; status.Margin = new Padding(0, 6, 0, 12);
            var links = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Margin = Padding.Empty };
            links.Controls.Add(details); links.Controls.Add(guide);
            diagnostic.MinimumSize = new Size(0, 130);
            foreach (Control control in new Control[] { heading, introduction, user, project, folders, status, progress, links, diagnostic }) {
                int row = content.RowCount++; content.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                content.Controls.Add(control, 0, row);
            }
            body.Controls.Add(content); layout.Controls.Add(body, 0, 0);
            var buttons = new FlowLayoutPanel { FlowDirection = FlowDirection.RightToLeft, WrapContents = false, Dock = DockStyle.Fill,
                AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Margin = new Padding(0, 18, 0, 0) };
            install.BackColor = Color.FromArgb(31, 101, 171); install.ForeColor = Color.White;
            buttons.Controls.Add(close); buttons.Controls.Add(install); layout.Controls.Add(buttons, 0, 1); Controls.Add(layout);
            content.SizeChanged += delegate { UpdateTextWidths(); };
            body.SizeChanged += delegate { UpdateTextWidths(); };
            Shown += delegate { FitToScreen(); UpdateTextWidths(); };
            project.CheckedChanged += delegate { browse.Enabled = project.Checked && !busy; folder.Enabled = project.Checked && !busy; };
            browse.Click += delegate { using (var dialog = new FolderBrowserDialog { Description = "Company Harness를 사용할 업무 폴더를 선택하세요.", ShowNewFolderButton = false }) if (dialog.ShowDialog(this) == DialogResult.OK) folder.Text = dialog.SelectedPath; };
            close.Click += delegate { Close(); }; install.Click += async delegate { await Install(); };
            details.LinkClicked += delegate {
                diagnostic.Visible = !diagnostic.Visible;
                if (diagnostic.Visible) { Height += diagnostic.MinimumSize.Height; FitToScreen(); body.ScrollControlIntoView(diagnostic); }
                UpdateTextWidths();
            };
            guide.LinkClicked += delegate { if (payloadRoot != null) Process.Start(new ProcessStartInfo(Path.Combine(payloadRoot, "bundle", "docs", "Company-Agent-사용자-안내서.html")) { UseShellExecute = true }); };
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (busy) { e.Cancel = true; status.Text = "설치가 끝나면 창을 닫을 수 있습니다."; } };
            AcceptButton = install; CancelButton = close;
            ResumeLayout(true);
        }
        private void UpdateTextWidths() {
            if (updatingWidths || body.ClientSize.Width <= 0) return;
            updatingWidths = true;
            try {
                int available = Math.Max(120, body.ClientSize.Width - (body.VerticalScroll.Visible ? SystemInformation.VerticalScrollBarWidth : 0));
                content.MaximumSize = new Size(available, 0);
                content.MinimumSize = new Size(available, 0);
                int width = Math.Max(120, available - content.Padding.Horizontal - 4);
                foreach (Label label in new Label[] { heading, introduction, status }) label.MaximumSize = new Size(width, 0);
            } finally { updatingWidths = false; }
        }
        private void FitToScreen() {
            Rectangle area = Screen.FromControl(this).WorkingArea;
            int margin = Math.Max(16, Font.Height);
            int width = Math.Max(320, area.Width - margin * 2), height = Math.Max(240, area.Height - margin * 2);
            MinimumSize = new Size(Math.Min(MinimumSize.Width, width), Math.Min(MinimumSize.Height, height));
            Size = new Size(Math.Min(Width, width), Math.Min(Height, height));
        }
        private void Busy(bool value) {
            if (value) busy = true;
            user.Enabled = !value; project.Enabled = !value;
            install.Enabled = !value; close.Enabled = !value; browse.Enabled = !value && project.Checked;
            progress.Visible = value;
            if (!value) busy = false;
        }
        private void Progress(string message) { if (!IsDisposed && IsHandleCreated) BeginInvoke(new Action(delegate { status.Text = message; })); }
        private string ChooseFile(string title, string filter) {
            using (var dialog = new OpenFileDialog { Title = title, Filter = filter, CheckFileExists = true }) return dialog.ShowDialog(this) == DialogResult.OK ? dialog.FileName : null;
        }
        private bool ConfirmReplacement() {
            using (var dialog = new Form { Text = "기존 하네스 확인", AutoScaleDimensions = new SizeF(96F, 96F), AutoScaleMode = AutoScaleMode.Dpi,
                AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
                Font = Font, StartPosition = FormStartPosition.CenterParent, FormBorderStyle = FormBorderStyle.FixedDialog,
                MaximizeBox = false, MinimizeBox = false }) {
                var panel = new TableLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, Padding = new Padding(20), ColumnCount = 1 };
                panel.Controls.Add(new Label { Text = "기존에 다른 하네스가 있습니다.\n백업 후 Company Harness로 바꾸면 기존 업무 지침과\n후크가 비활성화될 수 있습니다.", AutoSize = true, Margin = new Padding(0, 0, 0, 18) });
                var actions = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.RightToLeft, Dock = DockStyle.Top, WrapContents = false };
                var keep = new Button { Text = "기존 유지", AutoSize = true, Padding = new Padding(10, 5, 10, 5), DialogResult = DialogResult.Cancel };
                var replace = new Button { Text = "백업 후 설치", AutoSize = true, Padding = new Padding(10, 5, 10, 5), DialogResult = DialogResult.OK };
                actions.Controls.Add(replace); actions.Controls.Add(keep); panel.Controls.Add(actions); dialog.Controls.Add(panel);
                dialog.CancelButton = keep; dialog.AcceptButton = keep;
                return dialog.ShowDialog(this) == DialogResult.OK;
            }
        }
        private async Task Install() {
            if (project.Checked && !Directory.Exists(folder.Text)) { status.Text = "사용할 업무 폴더를 먼저 선택해 주세요."; return; }
            Busy(true); diagnostic.Visible = false; details.Visible = false; guide.Visible = false;
            status.Text = "설치 파일을 준비하고 기존 환경을 확인합니다…";
            var request = new Dictionary<string, object> { { "Scope", project.Checked ? "Project" : "User" }, { "SkillConflictAction", "KeepCurrent" } };
            if (project.Checked) request["ProjectRoot"] = folder.Text;
            try {
                payloadRoot = await Task.Run(() => Payload.Prepare(cacheRoot));
                for (int attempt = 0; attempt < 6; attempt++) {
                    var result = await Task.Run(() => Payload.Run(payloadRoot, request, Progress));
                    string state = Payload.Get(result, "status");
                    if (state == "installed" || state == "updated" || state == "reapplied") {
                        status.Text = "설치가 완료되었습니다.\nClaude Code를 닫았다 다시 열면 사용할 수 있습니다.";
                        guide.Visible = true; install.Visible = false;
                        string backup = Payload.Get(result, "safetyBackup");
                        diagnostic.Text = "적용 버전: " + Payload.Get(result, "coreVersion") + "\r\n백업 위치: " + backup;
                        details.Visible = true; return;
                    }
                    if (state == "kept" || state == "cancelled") { status.Text = "기존 구성을 유지했습니다. 설치 내용은 바꾸지 않았습니다."; return; }
                    if (state == "input-required") {
                        string input = Payload.Get(result, "input");
                        if (input == "ExistingHarnessAction") {
                            string rawChoices = Payload.Json.Serialize(result.ContainsKey("choices") ? result["choices"] : null);
                            if (rawChoices.Contains("\"Update\"")) { request["ExistingHarnessAction"] = "Update"; status.Text = "기존 Company Harness를 업데이트합니다…"; continue; }
                            if (!ConfirmReplacement()) { status.Text = "기존 하네스를 유지했습니다. 설치하지 않았습니다."; return; }
                            request["ExistingHarnessAction"] = "Replace"; continue;
                        }
                        if (input == "ClaudeCommand") {
                            string file = ChooseFile("평소 사용하는 Claude Code 실행 파일을 선택하세요.", "Claude 실행 파일|claude.exe;claude.cmd;claude.ps1|모든 파일|*.*");
                            if (file == null) { status.Text = "Claude Code 파일 선택을 취소했습니다."; return; }
                            request["ClaudeCommand"] = file; continue;
                        }
                        throw new IOException("설치에 필요한 항목을 확인해 주세요: " + input);
                    }
                    if (Payload.Get(result, "code") == "python_required") {
                        status.Text = "회사에서 준비한 Python 3.11 이상의 실행 파일을 선택해 주세요.";
                        string file = ChooseFile("준비된 Python 실행 파일을 선택하세요.", "Python 실행 파일|python.exe|모든 실행 파일|*.exe");
                        if (file == null) { status.Text = "Python 파일 선택을 취소했습니다. 설치하지 않았습니다."; return; }
                        request["PythonCommand"] = file; continue;
                    }
                    throw new IOException(Payload.Get(result, "detail") + "\n" + Payload.Get(result, "message"));
                }
                throw new IOException("필요한 설치 정보를 확인하지 못했습니다. 선택한 Claude Code와 Python 경로를 확인해 주세요.");
            } catch (Exception error) {
                status.Text = "설치를 완료하지 못했습니다. 자세히 보기에서 원인을 확인해 주세요.";
                diagnostic.Text = error.Message; details.Visible = true;
            } finally { Busy(false); }
        }
    }
}
