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
$stage = 'request'
$answer = @{ ok = $false; status = 'unknown'; code = 'office_failed'; message = 'PowerPoint could not finish. Original files and Office security settings were preserved.' }

function Get-ReportColor {
    param([string] $Hex)
    return [Convert]::ToInt32($Hex.Substring(0,2),16) + 256*[Convert]::ToInt32($Hex.Substring(2,2),16) + 65536*[Convert]::ToInt32($Hex.Substring(4,2),16)
}

function Add-ReportText {
    param($Slide, $Element, $Design)
    $shape = $Slide.Shapes.AddTextbox(1, $Element.x, $Element.y, $Element.w, $Element.h)
    $shape.TextFrame.WordWrap = -1
    $shape.TextFrame.MarginLeft = 0
    $shape.TextFrame.MarginRight = 0
    $shape.TextFrame.MarginTop = 2
    $shape.TextFrame.MarginBottom = 2
    $shape.TextFrame.TextRange.Text = [string]$Element.text
    $shape.TextFrame.TextRange.Font.Name = [string]$Design.font
    $shape.TextFrame.TextRange.Font.Size = [int]$Element.size
    $shape.TextFrame.TextRange.Font.Color.RGB = Get-ReportColor ([string]$Design.theme.($Element.color))
    $shape.TextFrame.TextRange.ParagraphFormat.SpaceBefore = 0
    $shape.TextFrame.TextRange.ParagraphFormat.SpaceAfter = 0
    if ($Element.bold) { $shape.TextFrame.TextRange.Font.Bold = -1 }
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
            $presentation.PageSetup.SlideWidth = [double]$request.spec.presentationPlan.width
            $presentation.PageSetup.SlideHeight = [double]$request.spec.presentationPlan.height
        }
        # If Office will not expose permission state, do not guess or export via
        # screenshots or alternative readers. Fail and report an unknown result.
        if ($presentation.Permission.Enabled) { throw 'protected_input' }
        if (-not $renderOnly) {
            $stage = 'layout'
            while ($presentation.Slides.Count -gt 0) { $presentation.Slides.Item(1).Delete() }
            $width = [double]$presentation.PageSetup.SlideWidth
            $height = [double]$presentation.PageSetup.SlideHeight
            $design = $request.spec.presentationPlan
            if ($null -eq $design -or @($design.pages).Count -ne @($request.spec.sections).Count) { throw 'missing_presentation_plan' }
            if ([Math]::Abs($design.width-$width) -gt 1 -or [Math]::Abs($design.height-$height) -gt 1) { throw 'page_size_changed' }
            $pageIndex = 0
            foreach ($row in @($request.spec.sections)) {
                $slide = $presentation.Slides.Add($presentation.Slides.Count + 1, 12)
                $slide.FollowMasterBackground = 0
                $slide.Background.Fill.Solid()
                $slide.Background.Fill.ForeColor.RGB = Get-ReportColor ([string]$design.theme.background)
                foreach ($element in @($design.pages[$pageIndex].elements)) {
                    $name = [string]$element.kind
                    $stage = $name
                    $left = [double]$element.x
                    $top = [double]$element.y
                    $blockWidth = [double]$element.w
                    $usable = [double]$element.h
                    if ($left -lt 0 -or $top -lt 0 -or $blockWidth -le 0 -or $usable -le 0 -or $left+$blockWidth -gt $width+1 -or $top+$usable -gt $height+1) { throw 'invalid_layout' }
                    if ($name -eq 'text') {
                        Add-ReportText -Slide $slide -Element $element -Design $design
                    }
                    elseif ($name -eq 'table') {
                        $headers = @($row.table.headers)
                        $rows = @($row.table.rows)
                        $table = $slide.Shapes.AddTable($rows.Count + 1, $headers.Count, $left, $top, $blockWidth, $usable).Table
                        for ($column = 0; $column -lt $headers.Count; $column++) {
                            $table.Columns.Item($column+1).Width = [double]$element.columnWidths[$column]
                        }
                        for ($r = 0; $r -le $rows.Count; $r++) {
                            $table.Rows.Item($r+1).Height = [double]$element.rowHeights[$r]
                            for ($c = 0; $c -lt $headers.Count; $c++) {
                                $cellShape = $table.Cell($r+1, $c+1).Shape
                                $cell = $cellShape.TextFrame.TextRange
                                if ($r -eq 0) { $cell.Text = [string]$headers[$c] } else { $cell.Text = [string]$rows[$r-1][$c] }
                                $cell.Font.Name = [string]$design.font
                                $cell.Font.Size = 16
                                $cell.Font.Bold = 0
                                $cellShape.TextFrame.MarginLeft = 6
                                $cellShape.TextFrame.MarginRight = 6
                                $cellShape.TextFrame.MarginTop = 2
                                $cellShape.TextFrame.MarginBottom = 2
                                $cellShape.TextFrame.VerticalAnchor = 3
                                $cellShape.Fill.Solid()
                                $cell.Font.Color.RGB = Get-ReportColor ([string]$design.theme.text)
                                $cellShape.Fill.ForeColor.RGB = Get-ReportColor ([string]$design.theme.background)
                                if ($r % 2 -eq 1) { $cellShape.Fill.ForeColor.RGB = Get-ReportColor ([string]$design.theme.tint) }
                                if ($r -eq 0) {
                                    $cell.Font.Bold = -1
                                    $cell.Font.Color.RGB = Get-ReportColor ([string]$design.theme.background)
                                    $cellShape.Fill.ForeColor.RGB = Get-ReportColor ([string]$design.theme.title)
                                }
                            }
                        }
                    }

                    elseif ($name -eq 'chart') {
                        $chartTypes = @{ column = 51; bar = 57; line = 4; pie = 5 }
                        $chart = $slide.Shapes.AddChart2(-1, [int]$chartTypes[[string]$row.chart.type], [single]$left, [single]$top, [single]$blockWidth, [single]$usable, $false).Chart
                        $chart.HasTitle = $false
                        $chart.ChartArea.Font.Name = [string]$design.font
                        $chart.ChartArea.Font.Size = 13
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
                        $chart.HasLegend = (@($row.chart.series).Count -gt 1 -or $row.chart.type -eq 'pie')
                        if ($chart.HasLegend) { $chart.Legend.Position = -4107 }
                        $colors = @([string]$design.theme.accent, [string]$design.theme.title, '52667C', 'B05C32')
                        for ($s = 1; $s -le $chart.SeriesCollection().Count; $s++) {
                            $serie = $chart.SeriesCollection($s)
                            $serie.Format.Fill.Solid()
                            $serie.Format.Fill.ForeColor.RGB = Get-ReportColor $colors[$s-1]
                            $serie.Format.Line.ForeColor.RGB = Get-ReportColor $colors[$s-1]
                        }
                        if ($row.chart.type -ne 'pie') {
                            $chart.Axes(1).TickLabels.Font.Size = 13
                            $chart.Axes(2).TickLabels.Font.Size = 12
                            if ($row.chart.type -in @('bar','column')) {
                                $values = @($row.chart.series | ForEach-Object { $_.values })
                                if (@($values | Where-Object { $_ -lt 0 }).Count -eq 0) { $chart.Axes(2).MinimumScale = 0 }
                            }
                        }
                        if (@($row.chart.categories).Count -le 6) { $chart.ApplyDataLabels() }
                    }
                    elseif ($name -eq 'image') {
                        # The request carries already inspected image bytes. Do
                        # not reread an arbitrary original path in this process.
                        $imageExtension = '.png'
                        if ([string]$row.image.mime -eq 'image/jpeg') { $imageExtension = '.jpg' }
                        $imagePath = Join-Path $workRoot ('image-' + [guid]::NewGuid().ToString('N') + $imageExtension)
                        [IO.File]::WriteAllBytes($imagePath, [Convert]::FromBase64String([string]$row.image.data))
                        $picture = $slide.Shapes.AddPicture($imagePath, 0, -1, $left, $top, -1, -1)
                        $picture.LockAspectRatio = -1
                        $picture.Height = $usable
                        if ($picture.Width -gt $blockWidth) { $picture.Width = $blockWidth }
                        $picture.Left = $left + ($blockWidth-$picture.Width)/2
                        $picture.Top = $top + ($usable-$picture.Height)/2
                        $picture.AlternativeText = [string]$row.image.alt
                    }
                }
                $pageIndex++
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
    # Bounded diagnostics contain no mail/document text, paths or raw Office errors.
    $answer.diagnostic = @{ stage = $stage; line = $_.InvocationInfo.ScriptLineNumber; hresult = $_.Exception.HResult }
    if ($stage -eq 'chart') {
        $answer.code = 'office_chart_unavailable'
        $answer.message = 'PowerPoint에서 편집 가능한 차트를 생성하지 못했습니다. 차트를 이미지로 바꾸거나 보안 설정을 변경하지 않았습니다. 설치된 PowerPoint/Excel의 차트 삽입 기능을 확인해 주세요.'
    }
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
