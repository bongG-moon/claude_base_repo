[CmdletBinding()]
param([Parameter(Mandatory = $true)][string] $RequestPath)

# Fixed Office operations only. The request contains data, never executable code.
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$application = $null
$presentation = $null
$security = $null
$answer = @{ ok = $false; status = 'unknown'; code = 'office_failed'; message = 'PowerPoint could not finish. Original files and Office security settings were preserved.' }

function Add-ReportText {
    param($Slide, [string] $Text, [double] $Top, [double] $Width, [double] $Height, [int] $Size, [bool] $Bold)
    $shape = $Slide.Shapes.AddTextbox(1, 40, $Top, $Width - 80, $Height)
    $shape.TextFrame.WordWrap = -1
    $shape.TextFrame.TextRange.Text = $Text
    $shape.TextFrame.TextRange.Font.Name = 'Malgun Gothic'
    $shape.TextFrame.TextRange.Font.Size = $Size
    if ($Bold) { $shape.TextFrame.TextRange.Font.Bold = -1 }
}

try {
    $request = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $outputPath = [IO.Path]::GetFullPath([string]$request.output)
    $workRoot = [IO.Path]::GetFullPath((Split-Path -Parent $RequestPath)).TrimEnd('\') + '\'
    # The Python caller supplies an isolated temporary working directory. Refuse
    # output or template paths outside it even if this helper is called directly.
    if (-not $outputPath.StartsWith($workRoot, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetExtension($outputPath) -ine '.pptx') {
        throw 'invalid_working_path'
    }
    $previewPath = [IO.Path]::GetFullPath([string]$request.previewDirectory)
    if (-not $previewPath.StartsWith($workRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'invalid_preview_path' }
    if ($request.spec.protected -eq $true -or $request.spec.drmRestricted -eq $true -or $request.spec.permissionGranted -eq $false) {
        throw 'protected_input'
    }
    $renderOnly = $request.renderOnly -eq $true
    if (-not $renderOnly -and (Test-Path -LiteralPath $outputPath)) { throw 'output_exists' }
    $type = [Type]::GetTypeFromProgID('PowerPoint.Application')
    if ($null -eq $type) {
        $answer = @{ ok = $false; status = 'unavailable'; code = 'powerpoint_unavailable'; message = 'Microsoft PowerPoint is not installed. No software was downloaded.' }
    }
    else {
        $application = New-Object -ComObject PowerPoint.Application
        $security = $application.AutomationSecurity
        # Force-disable macros before opening any supplied file. Never relax the
        # Trust Center, Protected View, IRM, sensitivity labels, or OS permissions.
        $application.AutomationSecurity = 3
        if ($renderOnly) {
            $presentation = $application.Presentations.Open($outputPath, -1, 0, 0)
        }
        elseif (-not [string]::IsNullOrWhiteSpace([string]$request.template)) {
            $templatePath = [IO.Path]::GetFullPath([string]$request.template)
            if (-not $templatePath.StartsWith($workRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'invalid_template_path' }
            $presentation = $application.Presentations.Open($templatePath, -1, -1, 0)
        }
        else {
            $presentation = $application.Presentations.Add(0)
            $presentation.PageSetup.SlideWidth = 960
            $presentation.PageSetup.SlideHeight = 540
        }
        # If Office will not expose permission state, do not guess or export via
        # screenshots or alternative readers. Fail and report an unknown result.
        if ($presentation.Permission.Enabled) { throw 'protected_input' }
        if (-not $renderOnly) {
            while ($presentation.Slides.Count -gt 0) { $presentation.Slides.Item(1).Delete() }
            $width = [double]$presentation.PageSetup.SlideWidth
            $height = [double]$presentation.PageSetup.SlideHeight
            foreach ($row in @($request.spec.sections)) {
                $slide = $presentation.Slides.Add($presentation.Slides.Count + 1, 12)
                Add-ReportText -Slide $slide -Text ([string]$row.title) -Top 20 -Width $width -Height 60 -Size 28 -Bold $true
                $blocks = New-Object System.Collections.Generic.List[string]
                foreach ($name in @('body', 'bullets', 'table', 'chart', 'image')) {
                    if ($row.$name -and @($row.$name).Count -gt 0) { $blocks.Add($name) }
                }
                $top = 96.0
                $blockHeight = ($height - 130) / [Math]::Max(1, $blocks.Count)
                foreach ($name in $blocks) {
                    $usable = [Math]::Max(36, $blockHeight - 8)
                    if ($name -eq 'body' -or $name -eq 'bullets') {
                        $text = [string]$row.body
                        if ($name -eq 'bullets') { $text = (@($row.bullets) -join "`r`n") }
                        Add-ReportText -Slide $slide -Text $text -Top $top -Width $width -Height $usable -Size 17 -Bold $false
                    }
                    elseif ($name -eq 'table') {
                        $headers = @($row.table.headers)
                        $rows = @($row.table.rows)
                        $table = $slide.Shapes.AddTable($rows.Count + 1, $headers.Count, 40, $top, $width - 80, $usable).Table
                        for ($column = 0; $column -lt $headers.Count; $column++) {
                            $table.Cell(1, $column + 1).Shape.TextFrame.TextRange.Text = [string]$headers[$column]
                        }
                        for ($r = 0; $r -lt $rows.Count; $r++) {
                            for ($c = 0; $c -lt $headers.Count; $c++) {
                                $cell = $table.Cell($r + 2, $c + 1).Shape.TextFrame.TextRange
                                $cell.Text = [string]$rows[$r][$c]
                                $cell.Font.Name = 'Malgun Gothic'
                                $cell.Font.Size = 12
                            }
                        }
                    }
                    elseif ($name -eq 'chart') {
                        $chartTypes = @{ column = 51; bar = 57; line = 4; pie = 5 }
                        $chart = $slide.Shapes.AddChart2(201, $chartTypes[[string]$row.chart.type], 40, $top, $width - 80, $usable).Chart
                        $chart.ChartData.Activate()
                        $book = $chart.ChartData.Workbook
                        try {
                            $sheet = $book.Worksheets.Item(1)
                            $sheet.Cells.Clear() | Out-Null
                            $categories = @($row.chart.categories)
                            $series = @($row.chart.series)
                            for ($c = 0; $c -lt $categories.Count; $c++) { $sheet.Cells.Item($c + 2, 1).Value2 = [string]$categories[$c] }
                            for ($s = 0; $s -lt $series.Count; $s++) {
                                $sheet.Cells.Item(1, $s + 2).Value2 = [string]$series[$s].name
                                for ($v = 0; $v -lt $categories.Count; $v++) { $sheet.Cells.Item($v + 2, $s + 2).Value2 = [double]$series[$s].values[$v] }
                            }
                            $range = $sheet.Range($sheet.Cells.Item(1, 1), $sheet.Cells.Item($categories.Count + 1, $series.Count + 1))
                            $chart.SetSourceData($range.Address($true, $true, 1, $true))
                        }
                        finally {
                            # Close only the embedded chart workbook opened here.
                            # Never quit Excel or close a user's unrelated document.
                            $book.Close($true)
                        }
                    }
                    elseif ($name -eq 'image') {
                        # The request carries already inspected image bytes. Do
                        # not reread an arbitrary original path in this process.
                        $imageExtension = '.png'
                        if ([string]$row.image.mime -eq 'image/jpeg') { $imageExtension = '.jpg' }
                        $imagePath = Join-Path $workRoot ('image-' + [guid]::NewGuid().ToString('N') + $imageExtension)
                        [IO.File]::WriteAllBytes($imagePath, [Convert]::FromBase64String([string]$row.image.data))
                        $picture = $slide.Shapes.AddPicture($imagePath, 0, -1, 40, $top, -1, -1)
                        $picture.LockAspectRatio = -1
                        $picture.Height = $usable
                        if ($picture.Width -gt ($width - 80)) { $picture.Width = $width - 80 }
                        $picture.AlternativeText = [string]$row.image.alt
                    }
                    $top += $blockHeight
                }
            }
            $presentation.SaveCopyAs($outputPath, 24)
        }
        # Export is the only rendering path. An Office denial must not trigger a
        # screenshot, conversion, OCR, print, or alternative-reader fallback.
        try {
            if (Test-Path -LiteralPath $previewPath) { throw 'preview_exists' }
            New-Item -ItemType Directory -Path $previewPath | Out-Null
            for ($i = 1; $i -le $presentation.Slides.Count; $i++) {
                $imageOutput = Join-Path $previewPath ('slide-{0:D3}.png' -f $i)
                $renderHeight = [int][Math]::Round(1600 * $presentation.PageSetup.SlideHeight / $presentation.PageSetup.SlideWidth)
                $presentation.Slides.Item($i).Export($imageOutput, 'PNG', 1600, $renderHeight)
            }
            $answer = @{ ok = $true; status = 'rendered'; rendered = $true; slides = $presentation.Slides.Count; editability = 'native-text-table-chart' }
        }
        catch {
            $answer = @{ ok = $false; status = 'unknown'; code = 'render_refused'; message = 'PowerPoint rendering was not completed. No alternative capture or protection bypass was attempted.' }
        }
    }
}
catch {
    if ($_.Exception.Message -eq 'protected_input') {
        $answer = @{ ok = $false; status = 'blocked'; code = 'protected_input'; message = 'Office reports restricted permissions. The operation was stopped without bypassing protection.' }
    }
}
finally {
    if ($null -ne $presentation) {
        try { $presentation.Saved = -1; $presentation.Close() } catch { }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation)
    }
    if ($null -ne $application) {
        if ($null -ne $security) { try { $application.AutomationSecurity = $security } catch { } }
        # PowerPoint may reuse the user's existing process. Do not call Quit or
        # kill processes, even after a failure. Release only our COM reference.
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($application)
    }
}
$answer | ConvertTo-Json -Depth 8 -Compress
