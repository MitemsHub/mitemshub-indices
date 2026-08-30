# Launch the live tick monitor DETACHED via WMI so it is not a child of the
# calling shell (the agent harness reaps shell children on exit).
$root = 'C:\Users\USER\Desktop\Projects\Synthetic Indices Bot'
$py   = Join-Path $root '.venv\Scripts\python.exe'
$mon  = Join-Path $root 'scripts\live_tick_monitor.py'
$log  = Join-Path $root 'artifacts\live_monitor.log'
$cl   = 'cmd /c ""{0}" -u "{1}" >> "{2}" 2>&1"' -f $py, $mon, $log
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine      = $cl
    CurrentDirectory = $root
}
Write-Output ("exit={0} pid={1}" -f $r.ReturnValue, $r.ProcessId)
