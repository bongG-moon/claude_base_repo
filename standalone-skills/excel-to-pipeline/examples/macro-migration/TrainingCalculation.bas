Attribute VB_Name = "TrainingCalculation"
Option Explicit

' A pure VBA calculation or a VBA -> worksheet formula -> VBA sequence.
' Examples only: native Excel compilation/execution is not part of this trial.

Public Sub CalculateMacroOnly(ByVal prepared As Object)
    Dim item As Variant, policy As Object, complete As Boolean
    Set policy = prepared("policy")
    For Each item In prepared("records")
        If IsEmpty(item("manual_amount")) Then
            item.Add "amount", Application.WorksheetFunction.Round( _
                item("unit_price") * item("quantity") * (1 - item("discount")), policy("digits"))
        Else
            item.Add "amount", item("manual_amount")
        End If
        complete = False
        If Not IsEmpty(item("score")) Then
            complete = item("attended_sessions") >= policy("required_sessions") _
                And item("exam_taken") And item("score") >= item("pass_score")
        End If
        item.Add "completed", complete
    Next item
End Sub

Public Sub CalculateMixed(ByVal prepared As Object)
    Dim scratch As Workbook, ws As Worksheet, item As Variant, r As Long, policy As Object
    Dim errorNumber As Long, errorText As String
    Set policy = prepared("policy")
    On Error GoTo Failed
    Set scratch = Application.Workbooks.Add(xlWBATWorksheet)
    Set ws = scratch.Worksheets(1)
    r = 2
    For Each item In prepared("records")
        ws.Cells(r, 1).Value = item("unit_price")
        ws.Cells(r, 2).Value = item("quantity")
        ws.Cells(r, 3).Value = item("discount")
        ws.Cells(r, 4).Value = item("manual_amount")
        ws.Cells(r, 5).Value = item("attended_sessions")
        ws.Cells(r, 6).Value = item("exam_taken")
        ws.Cells(r, 7).Value = item("score")
        ws.Cells(r, 8).Value = item("pass_score")
        ws.Cells(r, 9).Formula = "=IF(COUNTA(D" & r & ")=0,ROUND(A" & r & "*B" & r & _
            "*(1-C" & r & ")," & policy("digits") & "),D" & r & ")"
        ws.Cells(r, 10).Formula = "=AND(E" & r & ">=" & policy("required_sessions") & _
            ",F" & r & "=TRUE,COUNTA(G" & r & ")>0,G" & r & ">=H" & r & ")"
        r = r + 1
    Next item
    ws.Calculate
    r = 2
    For Each item In prepared("records")
        If IsError(ws.Cells(r, 9).Value) Or IsError(ws.Cells(r, 10).Value) Then
            Err.Raise vbObjectError + 720, , "Mixed formula calculation failed"
        End If
        item.Add "amount", ws.Cells(r, 9).Value
        item.Add "completed", CBool(ws.Cells(r, 10).Value)
        r = r + 1
    Next item
    scratch.Close SaveChanges:=False
    Exit Sub
Failed:
    errorNumber = Err.Number: errorText = Err.Description
    On Error Resume Next
    If Not scratch Is Nothing Then scratch.Close SaveChanges:=False
    On Error GoTo 0
    Err.Raise errorNumber, , errorText
End Sub

Public Sub AggregateDepartments(ByVal prepared As Object)
    Dim result As Object, totals As Object, item As Variant, department As String
    Dim totalAmount As Double, completedCount As Long
    Set result = NewMap()
    For Each item In prepared("records")
        department = item("department")
        If Not result.Exists(department) Then
            Set totals = NewMap()
            totals.Add "department", department
            totals.Add "approved_count", 0
            totals.Add "total_amount", 0#
            totals.Add "completed_count", 0
            result.Add department, totals
        End If
        Set totals = result(department)
        totals("approved_count") = totals("approved_count") + 1
        totals("total_amount") = totals("total_amount") + item("amount")
        If item("completed") Then
            totals("completed_count") = totals("completed_count") + 1
            completedCount = completedCount + 1
        End If
        totalAmount = totalAmount + item("amount")
    Next item
    prepared.Add "departments", result
    prepared.Add "total_amount", totalAmount
    prepared.Add "completed_count", completedCount
End Sub

Public Function RunTraining(ByVal source As Workbook, Optional ByVal mixed As Boolean = False, _
        Optional ByVal includeExceptions As Boolean = False) As Object
    Dim prepared As Object
    Set prepared = PrepareTraining(source, includeExceptions)
    If mixed Then
        CalculateMixed prepared
    Else
        CalculateMacroOnly prepared
    End If
    AggregateDepartments prepared
    Set RunTraining = prepared
End Function
