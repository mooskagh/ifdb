go build -ldflags "-s -w -H=windowsgui"
call "C:\Program Files (x86)\Microsoft Visual Studio 14.0\Common7\Tools\"vsvars32.bat
signtool sign /v /f D:\My\Cert\MySPC.pfx /t http://timestamp.verisign.com/scripts/timstamp.dll loonchator.exe