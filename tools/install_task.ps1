# Registers a per-user scheduled task that keeps the practice runner alive.
# It starts at logon and re-checks every 5 minutes. IgnoreNew and the runner's
# account lock together mean a live runner is never duplicated and a dead one is restarted.
param(
    [string]$TaskName = "GoldBotRunner",
    [string]$RunArgs = "-m goldbot run --strategy scalp38 --ladder --data-dir data/scalp38_ladder --risk 0.001 --execute"
)

$repo = Split-Path -Parent $PSScriptRoot
$pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source

$action = New-ScheduledTaskAction -Execute $pythonw -Argument $RunArgs -WorkingDirectory $repo
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$every5 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $atLogon, $every5 `
    -Settings $settings -Principal $principal -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
