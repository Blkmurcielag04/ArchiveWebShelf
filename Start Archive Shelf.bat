@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Python was not found at "%PYTHON_EXE%".
  echo Edit this launcher to point to your installed python.exe.
  pause
  exit /b 1
)
echo Checking for an existing Archive Shelf server...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Write-Host 'Checking ports 8765-8794...'; $listenerPorts = @(netstat.exe -ano -p tcp | ForEach-Object { if ($_ -match '^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+\d+\s*$') { $port = [int]$Matches[1]; if ($port -ge 8765 -and $port -lt 8795) { $port } } } | Sort-Object -Unique); $existingPort = $null; foreach ($port in $listenerPorts) { try { $state = Invoke-RestMethod ('http://127.0.0.1:' + $port + '/api/state') -TimeoutSec 2; if ($state.application -eq 'archive-shelf' -and $state.items -is [array]) { $existingPort = $port; break } } catch {} }; if ($null -eq $existingPort) { Write-Host 'No existing Archive Shelf server found.' } else { Write-Host ('Archive Shelf is already running on port ' + $existingPort + '.'); Write-Host 'Restart it with the updated files? Do not restart during a recording save.'; $answer = Read-Host 'Restart now? (Y/N)'; if ($answer -match '^(y|yes)$') { $pattern = '^\s*TCP\s+\S+:' + $existingPort + '\s+\S+\s+LISTENING\s+(\d+)\s*$'; $rows = @(netstat.exe -ano -p tcp | Select-String -Pattern $pattern); $processIds = @(); foreach ($row in $rows) { if ($row.Line -match $pattern) { $processIds += [int]$Matches[1] } }; $processIds = @($processIds | Select-Object -Unique); if ($processIds.Count -eq 0) { Write-Host 'Could not find the process listening on the Archive Shelf port.'; exit 3 }; foreach ($processId in $processIds) { $owner = Get-Process -Id $processId -ErrorAction SilentlyContinue; if ($null -eq $owner -or $owner.ProcessName -notin @('python','pythonw')) { Write-Host ('Port owner ' + $processId + ' is not a Python server. Nothing was stopped.'); exit 3 } }; foreach ($processId in $processIds) { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Seconds 1; try { $check = Invoke-RestMethod ('http://127.0.0.1:' + $existingPort + '/api/state') -TimeoutSec 1; if ($check.application -eq 'archive-shelf') { Write-Host 'The old server is still responding. Nothing new was started.'; exit 3 } } catch {} } }"
if errorlevel 3 (
  echo The existing server was not stopped. Nothing was changed.
  pause
  exit /b 1
)
:launch_server
echo Starting Archive Shelf...
"%PYTHON_EXE%" "%~dp0organizer_server.py"
if errorlevel 1 echo Archive Shelf exited with an error.
echo.
echo Archive Shelf stopped.
choice /C RC /N /M "Press R to restart Archive Shelf, or C to close this window."
if errorlevel 2 exit /b 0
goto launch_server
