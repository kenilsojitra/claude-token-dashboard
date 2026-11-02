' Double-click to stop the tracker and remove it from Windows startup.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)

lnkPath = sh.SpecialFolders("Startup") & "\Claude Token Dashboard (User).lnk"
If fso.FileExists(lnkPath) Then fso.DeleteFile lnkPath

port = "18765"
portFile = dir & "\data\port.txt"
If fso.FileExists(portFile) Then
  Set f = fso.OpenTextFile(portFile, 1)
  p = Trim(f.ReadAll)
  f.Close
  If p <> "" Then port = p
End If

On Error Resume Next
Set http = CreateObject("MSXML2.XMLHTTP")
http.Open "POST", "http://127.0.0.1:" & port & "/api/stop", False
http.setRequestHeader "X-Dashboard", "1"
http.Send
On Error GoTo 0

MsgBox "Stopped and removed from startup." & vbCrLf & "Your saved counts are kept in the data folder.", 64, "Claude Token Dashboard - User"
