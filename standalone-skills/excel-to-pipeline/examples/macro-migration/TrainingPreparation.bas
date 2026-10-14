Attribute VB_Name = "TrainingPreparation"
Option Explicit

' Reviewed synthetic business example. Not imported or executed by the Python test.
' No file, mail, HTTP, shell, registry or database operations.

Public Function NewMap() As Object
    Set NewMap = CreateObject("Scripting.Dictionary")
    NewMap.CompareMode = vbBinaryCompare
End Function

Public Function CodeOf(ByVal value As Variant) As String
    If IsEmpty(value) Or IsNull(value) Then Exit Function
    CodeOf = UCase$(Trim$(CStr(value)))
End Function

Public Function IsBlank(ByVal value As Variant) As Boolean
    If IsEmpty(value) Or IsNull(value) Then
        IsBlank = True
    ElseIf VarType(value) = vbString Then
        IsBlank = (Len(Trim$(value)) = 0)
    End If
End Function

Public Function ReadRows(ByVal book As Workbook, ByVal sheetName As String, ByVal width As Long) As Collection
    Dim ws As Worksheet, last As Range, r As Long, c As Long, item As Object
    Dim nonEmpty As Boolean, result As New Collection
    Set ws = book.Worksheets(sheetName)
    Set last = ws.Range(ws.Cells(6, 2), ws.Cells(ws.Rows.Count, width + 1)).Find( _
        What:="*", LookIn:=xlFormulas, SearchOrder:=xlByRows, SearchDirection:=xlPrevious)
    If last Is Nothing Then
        Set ReadRows = result
        Exit Function
    End If
    For r = 6 To last.Row
        Set item = NewMap()
        nonEmpty = False
        For c = 2 To width + 1
            item.Add CStr(ws.Cells(5, c).Value), ws.Cells(r, c).Value
            If Not IsBlank(ws.Cells(r, c).Value) Then nonEmpty = True
        Next c
        If nonEmpty Then
            item.Add "source_sheet", sheetName
            item.Add "source_row", r
            result.Add item
        End If
    Next r
    Set ReadRows = result
End Function

Public Function NumericValue(ByVal value As Variant, ByVal field As String, _
        ByVal minimum As Double, ByVal maximum As Double, Optional ByVal whole As Boolean = False) As Double
    If IsBlank(value) Or VarType(value) = vbBoolean Or Not IsNumeric(value) Then
        Err.Raise vbObjectError + 701, , field & ": numeric value required"
    End If
    NumericValue = CDbl(value)
    If NumericValue < minimum Or NumericValue > maximum Then
        Err.Raise vbObjectError + 702, , field & ": outside allowed range"
    End If
    If whole And NumericValue <> Fix(NumericValue) Then
        Err.Raise vbObjectError + 703, , field & ": integer required"
    End If
End Function

Public Function BooleanFlag(ByVal value As Variant) As Boolean
    Select Case CodeOf(value)
        Case "Y", "TRUE", "1", "참석", "응시": BooleanFlag = True
        Case "N", "FALSE", "0", "불참", "미응시", "": BooleanFlag = False
        Case Else: Err.Raise vbObjectError + 704, , "Unknown boolean flag"
    End Select
End Function

Public Function IsoDate(ByVal value As Variant) As String
    Dim s As String, parsed As Date
    If VarType(value) = vbDate Then
        IsoDate = Format$(value, "yyyy-mm-dd")
        Exit Function
    End If
    s = Trim$(CStr(value))
    If Not s Like "####-##-##" Then Err.Raise vbObjectError + 705, , "Date must be YYYY-MM-DD"
    parsed = DateSerial(CLng(Left$(s, 4)), CLng(Mid$(s, 6, 2)), CLng(Right$(s, 2)))
    If Format$(parsed, "yyyy-mm-dd") <> s Then Err.Raise vbObjectError + 706, , "Invalid calendar date"
    IsoDate = s
End Function

Public Function UniqueIndex(ByVal rows As Collection, ByVal field As String) As Object
    Dim item As Variant, key As String, result As Object
    Set result = NewMap()
    For Each item In rows
        key = CodeOf(item(field))
        If key = "" Or result.Exists(key) Then Err.Raise vbObjectError + 707, , "Empty or duplicate reference key"
        result.Add key, item
    Next item
    Set UniqueIndex = result
End Function

Public Function Notice(ByVal item As Object, ByVal reason As String) As Object
    Set Notice = NewMap()
    Notice.Add "application_id", CodeOf(item("신청ID"))
    Notice.Add "source_sheet", item("source_sheet")
    Notice.Add "source_row", item("source_row")
    Notice.Add "reason", reason
End Function

Public Function LatestApplications(ByVal rows As Collection, ByVal rejected As Collection, _
        ByVal superseded As Collection) As Object
    Dim latest As Object, item As Variant, previous As Object, key As String
    Dim revision As Double, issue As String
    Set latest = NewMap()
    For Each item In rows
        key = CodeOf(item("신청ID"))
        issue = ""
        On Error Resume Next
        revision = NumericValue(item("갱신순번"), "revision", 0, 1E+15, True)
        issue = Err.Description
        Err.Clear
        On Error GoTo 0
        If key = "" Then issue = "Missing application ID"
        If issue <> "" Then
            rejected.Add Notice(item, issue)
        ElseIf Not latest.Exists(key) Then
            latest.Add key, item
        Else
            Set previous = latest(key)
            If revision >= CDbl(previous("갱신순번")) Then
                superseded.Add Notice(previous, "Replaced by higher revision or later tied row")
                Set latest(key) = item
            Else
                superseded.Add Notice(item, "Older revision")
            End If
        End If
    Next item
    Set LatestApplications = latest
End Function

Public Function AttendanceCount(ByVal rows As Collection, ByVal applicationId As String) As Long
    Dim item As Variant, sessions As Object, session As String, attended As Boolean
    Set sessions = NewMap()
    For Each item In rows
        If CodeOf(item("신청ID")) = applicationId Then
            session = CStr(NumericValue(item("차시"), "session", 1, 1E+9, True))
            attended = BooleanFlag(item("참석"))
            If attended And Not sessions.Exists(session) Then sessions.Add session, True
        End If
    Next item
    AttendanceCount = sessions.Count
End Function

Public Function Assessment(ByVal rows As Collection, ByVal applicationId As String) As Object
    Dim item As Variant, result As Object, taken As Boolean, score As Variant
    Set result = NewMap()
    result.Add "exam_taken", False
    result.Add "score", Empty
    For Each item In rows
        If CodeOf(item("신청ID")) = applicationId Then
            taken = BooleanFlag(item("응시"))
            score = Empty
            If Not IsBlank(item("점수")) Then score = NumericValue(item("점수"), "score", 0, 100)
            If taken And IsEmpty(score) Then Err.Raise vbObjectError + 708, , "Exam taken but score missing"
            result("exam_taken") = taken
            result("score") = score
        End If
    Next item
    Set Assessment = result
End Function

Private Function PrepareOne(ByVal item As Object, ByVal staff As Object, ByVal courses As Object, _
        ByVal attendance As Collection, ByVal exams As Collection, ByVal policy As Object) As Object
    Dim employeeId As String, courseCode As String, department As String, applicationId As String
    Dim employee As Object, course As Object, exam As Object, result As Object, scoreLimit As Double
    If VarType(item("사번")) <> vbString Then Err.Raise vbObjectError + 709, , "Employee ID must be text"
    employeeId = CodeOf(item("사번")): courseCode = CodeOf(item("과정코드"))
    applicationId = CodeOf(item("신청ID")): department = Trim$(CStr(item("부서")))
    If Not staff.Exists(employeeId) Then Err.Raise vbObjectError + 710, , "Unknown employee"
    If Not courses.Exists(courseCode) Then Err.Raise vbObjectError + 711, , "Unknown course"
    Set employee = staff(employeeId): Set course = courses(courseCode)
    If department <> Trim$(CStr(employee("부서"))) Then Err.Raise vbObjectError + 712, , "Department mismatch; not corrected"
    Set result = NewMap()
    result.Add "application_id", applicationId
    result.Add "employee_id", employeeId
    result.Add "department", department
    result.Add "course_code", courseCode
    result.Add "training_date", IsoDate(item("교육일"))
    result.Add "quantity", NumericValue(item("수량"), "quantity", 0, 1E+15, True)
    result.Add "discount", NumericValue(item("할인율"), "discount", 0, 1)
    result.Add "manual_amount", Empty
    If Not IsBlank(item("수동금액")) Then result("manual_amount") = NumericValue(item("수동금액"), "override", 0, 1E+15)
    result.Add "unit_price", NumericValue(course("단가"), "unit price", 0, 1E+15)
    scoreLimit = policy("default_score")
    If Not IsBlank(course("수료점수")) Then scoreLimit = NumericValue(course("수료점수"), "pass score", 0, 100)
    result.Add "pass_score", scoreLimit
    result.Add "attended_sessions", AttendanceCount(attendance, applicationId)
    Set exam = Assessment(exams, applicationId)
    result.Add "exam_taken", exam("exam_taken")
    result.Add "score", exam("score")
    result.Add "source_sheet", item("source_sheet")
    result.Add "source_row", item("source_row")
    result.Add "round", Trim$(CStr(item("회차")))
    Set PrepareOne = result
End Function

Public Function PrepareTraining(ByVal book As Workbook, Optional ByVal includeExceptions As Boolean = False) As Object
    Dim applications As Collection, attendance As Collection, exams As Collection, additional As Collection
    Dim staff As Object, courses As Object, policies As Object, policy As Object, latest As Object
    Dim accepted As New Collection, excluded As New Collection, rejected As New Collection, superseded As New Collection
    Dim item As Variant, key As Variant, record As Object, result As Object, status As String, issue As String
    Set applications = ReadRows(book, "신청원본", 12)
    If includeExceptions Then
        Set additional = ReadRows(book, "예외신청", 12)
        For Each item In additional: applications.Add item: Next item
    End If
    Set attendance = ReadRows(book, "출결원본", 4)
    Set exams = ReadRows(book, "평가원본", 3)
    Set staff = UniqueIndex(ReadRows(book, "사원기준", 5), "사번")
    Set courses = UniqueIndex(ReadRows(book, "교육기준", 5), "과정코드")
    Set policies = UniqueIndex(ReadRows(book, "정책", 2), "항목")
    Set policy = NewMap()
    policy.Add "required_sessions", NumericValue(policies("필수참석차시")("값"), "sessions required", 1, 100, True)
    policy.Add "default_score", NumericValue(policies("기본수료점수")("값"), "default pass score", 0, 100)
    policy.Add "digits", NumericValue(policies("금액소수자리")("값"), "money decimals", 0, 4, True)
    Set latest = LatestApplications(applications, rejected, superseded)
    For Each key In latest.Keys
        Set item = latest(key)
        status = Trim$(CStr(item("상태")))
        If status = "대기" Or status = "취소" Then
            excluded.Add Notice(item, status)
        ElseIf status <> "승인" Then
            rejected.Add Notice(item, "Unknown application status")
        Else
            issue = "": Set record = Nothing
            On Error Resume Next
            Set record = PrepareOne(item, staff, courses, attendance, exams, policy)
            issue = Err.Description
            Err.Clear
            On Error GoTo 0
            If issue = "" Then
                accepted.Add record
            Else
                rejected.Add Notice(item, issue)
            End If
        End If
    Next key
    Set result = NewMap()
    result.Add "records", accepted
    result.Add "excluded", excluded
    result.Add "rejected", rejected
    result.Add "superseded", superseded
    result.Add "policy", policy
    result.Add "input_rows", applications.Count
    result.Add "deduplicated_rows", latest.Count
    Set PrepareTraining = result
End Function
