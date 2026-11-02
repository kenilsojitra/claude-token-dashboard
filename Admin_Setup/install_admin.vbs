' Double-click ONCE on the admin PC.
' 1) installs Python automatically if this PC does not have it (needs internet once)
' 2) starts the admin server now (hidden) and every time you log in to Windows
' 3) opens the Admin dashboard in the browser
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
startup = sh.SpecialFolders("Startup")
ttl = "Claude Token Dashboard - Admin"

rc = sh.Run("cmd /c """ & dir & "\ensure_python.bat""", 1, True)
If rc <> 0 Then
  MsgBox "Python could not be installed automatically." & vbCrLf & vbCrLf & _
    "Please check the internet connection and double-click install_admin.vbs again," & vbCrLf & _
    "or install Python 3 yourself from https://www.python.org/downloads/ (tick 'Add python.exe to PATH').", 48, ttl
  WScript.Quit 1
End If

Set lnk = sh.CreateShortcut(startup & "\Claude Token Dashboard (Admin).lnk")
lnk.TargetPath = "wscript.exe"
lnk.Arguments = """" & dir & "\run_hidden.vbs"""
lnk.WorkingDirectory = dir
lnk.Description = "Claude Token Dashboard - Admin (background)"
lnk.Save

sh.Run "wscript.exe """ & dir & "\run_hidden.vbs""", 0, False

MsgBox "Installed." & vbCrLf & vbCrLf & _
  "The admin server now runs in the background and starts by itself when you log in." & vbCrLf & vbCrLf & _
  "Click OK - the Admin dashboard opens in the browser." & vbCrLf & _
  "First time: create the admin password, then use 'Add user' for every user." & vbCrLf & vbCrLf & _
  "If Windows asks about the firewall, choose 'Allow access' (Private networks)." & vbCrLf & _
  "Do not move or delete this folder.", 64, ttl

sh.Run "wscript.exe """ & dir & "\open_admin.vbs""", 0, False
