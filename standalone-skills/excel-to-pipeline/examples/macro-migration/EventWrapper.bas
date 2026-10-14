Attribute VB_Name = "EventWrapper"
Option Explicit

' Explicit button handler. This file is a standard module, NOT ThisWorkbook.
' No Workbook_Open, Auto_Open or automatic Worksheet_Change registration.
' If an existing workbook calls this from an event, document that event and its
' ordering before migrating it. Python replaces that trigger with one explicit run.

Public Sub TrainingButtonClick()
    Dim result As Object
    Set result = RunTraining(ThisWorkbook, False, False)
    Debug.Print "Approved applications: "; result("records").Count
    Debug.Print "Amount: "; result("total_amount")
End Sub

Public Sub MixedTrainingButtonClick()
    Dim result As Object
    Set result = RunTraining(ThisWorkbook, True, False)
    Debug.Print "Approved applications: "; result("records").Count
    Debug.Print "Amount: "; result("total_amount")
End Sub
