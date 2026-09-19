param([ValidateSet('folder', 'files')][string]$Kind)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.Show()
$paths = @()
try {
    if ($Kind -eq 'folder') {
        $dialog = New-Object Windows.Forms.FolderBrowserDialog
        $dialog.Description = 'Select a trusted work folder'
        if ($dialog.ShowDialog($owner) -eq 'OK') { $paths = @($dialog.SelectedPath) }
    } else {
        $dialog = New-Object Windows.Forms.OpenFileDialog
        $dialog.Multiselect = $true
        $dialog.Filter = 'Documents and images|*.pptx;*.docx;*.xlsx;*.csv;*.tsv;*.pdf;*.txt;*.md;*.html;*.png;*.jpg;*.jpeg;*.webp'
        if ($dialog.ShowDialog($owner) -eq 'OK') { $paths = @($dialog.FileNames) }
    }
    ConvertTo-Json -InputObject @($paths) -Compress
} finally {
    if ($dialog) { $dialog.Dispose() }
    $owner.Close()
    $owner.Dispose()
}
