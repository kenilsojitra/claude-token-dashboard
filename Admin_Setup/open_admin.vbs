' Double-click to open the Admin dashboard (starts the server first if it is not running).
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)

Function GetPort()
  GetPort = "18800"
  portFile = dir & "\data\port.txt"
  If fso.FileExists(portFile) Then
    Set f = fso.OpenTextFile(portFile, 1)
    p = Trim(f.ReadAll)
    f.Close
    If p <> "" Then GetPort = p
  End If
End Function

Function IsRunning(port)
  IsRunning = False
  On Error Resume Next
  Set http = CreateObject("MSXML2.XMLHTTP")
  http.Open "GET", "http://127.0.0.1:" & port & "/api/ping", False
  http.Send
  If Err.Number = 0 Then
    If InStr(http.responseText, "ctd-admin") > 0 Then IsRunning = True
  End If
  On Error GoTo 0
End Function

Function LogTail(path)
  LogTail = ""
  If Not fso.FileExists(path) Then Exit Function
  size = fso.GetFile(path).Size
  Set f = fso.OpenTextFile(path, 1)
  If size > 3000 Then f.Skip size - 3000
  txt = f.ReadAll
  f.Close
  parts = Split(txt, vbLf)
  last = UBound(parts)
  first = last - 7
  If first < 0 Then first = 0
  out = ""
  For i = first To last
    out = out & Replace(parts(i), vbCr, "") & vbCrLf
  Next
  If Len(out) > 700 Then out = Right(out, 700)
  LogTail = out
End Function

port = GetPort()
If Not IsRunning(port) Then
  sh.Run "wscript.exe """ & dir & "\run_hidden.vbs""", 0, False
  For i = 1 To 30
    WScript.Sleep 1000
    port = GetPort()
    If IsRunning(port) Then Exit For
  Next
End If

If Not IsRunning(port) Then
  MsgBox "The admin dashboard could not be started." & vbCrLf & vbCrLf & _
    "Double-click install_admin.vbs again (it installs Python if it is missing)." & vbCrLf & _
    "Last lines of data\admin.log:" & vbCrLf & LogTail(dir & "\data\admin.log"), 48, "Claude Token Dashboard - Admin"
  WScript.Quit 1
End If

sh.Run "http://127.0.0.1:" & port & "/"
