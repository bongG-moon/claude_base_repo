# A local, interactive approval surface. No command is supplied by the caller.
$ErrorActionPreference = 'Stop'
try {
    [Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if (-not [Environment]::UserInteractive) { throw 'Interactive user required.' }
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object System.Windows.Forms.Form
    $form.Text = [string]$request.title
    $form.Width = 800
    $form.Height = 650
    $form.StartPosition = 'CenterScreen'
    $form.TopMost = $true
    $text = New-Object System.Windows.Forms.TextBox
    $text.Multiline = $true
    $text.MaxLength = 524288
    $text.ReadOnly = $true
    $text.ScrollBars = 'Both'
    $text.WordWrap = $false
    $text.Dock = 'Fill'
    $text.Text = ([string]$request.details).Replace("`n", "`r`n")
    $panel = New-Object System.Windows.Forms.FlowLayoutPanel
    $panel.Dock = 'Bottom'
    $panel.Height = 60
    $yes = New-Object System.Windows.Forms.Button
    $yes.Text = -join ([char]0xC2B9, [char]0xC778)
    $yes.Width = 150
    $yes.Height = 42
    $yes.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $no = New-Object System.Windows.Forms.Button
    $no.Text = -join ([char]0xCDE8, [char]0xC18C)
    $no.Width = 150
    $no.Height = 42
    $no.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $panel.Controls.Add($no)
    $panel.Controls.Add($yes)
    $form.Controls.Add($text)
    $form.Controls.Add($panel)
    $form.CancelButton = $no
    # Enter must not silently accept a destructive plan.
    $form.AcceptButton = $no
    if ($env:COMPANY_AGENT_OFFICE_PROGRESS -eq '1') {
        $form.Add_Shown({
            [Console]::Error.WriteLine('CA_OFFICE_STAGE:confirmation_wait')
            [Console]::Error.Flush()
        })
    }
    $approved = $form.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK
    $form.Dispose()
    @{ approved = [bool]$approved } | ConvertTo-Json -Compress
} catch {
    '{"approved":false}'
    exit 1
}
