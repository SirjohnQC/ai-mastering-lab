@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title AI Mastering Lab - First Push Repair v3
set "DEST=https://github.com/SirjohnQC/ai-mastering-lab.git"
echo =======================================================
echo AI MASTERING LAB - GITHUB PUSH REPAIR v3
 echo =======================================================
echo Project directory: %CD%
echo Destination: %DEST%
echo.
where git >nul 2>nul
if errorlevel 1 goto :nogit
where powershell >nul 2>nul
if errorlevel 1 goto :nopowershell
if not exist "src\mastering_lab" (
 echo [STOP] This script must be in your project root with src\mastering_lab.
 goto :finish
)
if not exist ".git" (
 echo [INFO] Git was not initialized. Initializing now...
 git init
 if errorlevel 1 goto :error
 git branch -M main
 if errorlevel 1 goto :error
)
echo [1/7] Current repository state:
git status --short
echo.
echo [2/7] Making sure the ENTIRE audio directory stays local...
(
 echo.
 echo # AI-MASTERING-LAB AUDIO LOCAL ONLY
 echo audio/
 echo Audio/
 echo AUDIO/
 echo *.wav
 echo *.mp3
 echo *.flac
 echo *.aiff
 echo *.aif
 echo *.m4a
 echo *.ogg
 echo *.opus
 echo settings/
 echo stems/
 echo stem/
 echo masters/
 echo recordings/
 echo sound/
 echo outputs/
 echo output/
 echo cache/
 echo logs/
 echo .env
 echo .env.*
 echo *.pem
 echo *.key
 echo *.pfx
 echo *.p12
 echo *.vst3
 echo *.dll
 echo *.exe
 echo *.zip
 echo *.state
 echo .vscode/
 echo *.egg-info/
 echo *.pre_probe_backup.cpp
 echo build/
 echo native/build/
 echo __pycache__/
 echo .venv/
) >> ".gitignore"
echo.
echo [3/7] Staging source while respecting .gitignore...
git add -A
if errorlevel 1 goto :error
echo The following files WOULD enter a commit:
git --no-pager diff --cached --stat
if errorlevel 1 goto :error
echo.
echo [4/7] SAFETY SCAN OF STAGED FILES AND ANY EXISTING HISTORY...
set "AML_SECURITY_OK="
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $patterns='(?i)(^|/)(audio|stems?|masters?|recordings?|references?|sound|settings|cache|outputs?|\.vscode|\.ssh|\.aws)/|(?i)\.(wav|mp3|flac|aiff|aif|m4a|ogg|opus|mp4|mov|mkv|vst3|dll|exe|zip|pem|key|pfx|p12|state)$|(?i)(^|/)[^/]+\.egg-info/|(?i)(^|/)\.env(\..*)?$'; $staged=@(git -c core.quotepath=false diff --cached --name-only --diff-filter=ACMR); if($LASTEXITCODE -ne 0){throw 'git diff failed'}; $bad=@($staged | Where-Object {$_ -match $patterns}); foreach($s in $staged){if(Test-Path -LiteralPath $s -PathType Leaf){if((Get-Item -LiteralPath $s).Length -gt 20MB){$bad+=($s+' [OVER 20MB]')}}}; $commits=@(git rev-list --all); if($LASTEXITCODE -ne 0){throw 'git history scan failed'}; if($commits.Count -gt 0){foreach($sha in $commits){$entries=@(git -c core.quotepath=false ls-tree -r --name-only $sha); if($LASTEXITCODE -ne 0){throw 'git ls-tree failed'}; $bad+=@($entries | Where-Object {$_ -match $patterns} | ForEach-Object {$_+' [IN HISTORY '+$sha.Substring(0,7)+']'})}}; $bad=@($bad | Select-Object -Unique); if($bad.Count){Write-Host '[BLOCKED] Private files in staged changes or history:' -ForegroundColor Red; $bad | Select-Object -First 60 | ForEach-Object {Write-Host ('  '+$_)}; exit 9}; $secrets=@(git grep --cached -I -l -E '(-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|ghp_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{25,})' -- . 2>$null); if($LASTEXITCODE -gt 1){throw 'credential scan failed'}; if($secrets.Count){Write-Host '[BLOCKED] Files possibly containing secrets:' -ForegroundColor Red; $secrets | ForEach-Object {Write-Host ('  '+$_)}; exit 9}; Write-Host '[OK] No known private media or secrets detected. Manual inspection is still required.' -ForegroundColor Green"
if errorlevel 1 goto :blocked
echo.
echo [5/7] Review the staged filenames carefully:
git --no-pager diff --cached --name-only
echo.
echo IMPORTANT: This repository is PUBLIC. Review files for personal data.
choice /C YN /M "Are these files safe to publish to PUBLIC GitHub"
if errorlevel 2 goto :cancel
for /f "delims=" %%G in ('git remote get-url origin 2^>nul') do set "ORIGIN=%%G"
if defined ORIGIN goto :checkorigin
git remote add origin "%DEST%"
if errorlevel 1 goto :error
set "ORIGIN=%DEST%"
:checkorigin
if /I "%ORIGIN%"=="%DEST%" goto :goodorigin
if /I "%ORIGIN%"=="git@github.com:SirjohnQC/ai-mastering-lab.git" goto :goodorigin
echo [BLOCKED] Unexpected remote: %ORIGIN%
goto :finish
:goodorigin
echo.
echo [6/7] Creating commit if necessary...
git diff --cached --quiet
if errorlevel 1 (
 git commit -m "Initial open-source AI Mastering Lab"
 if errorlevel 1 goto :commiterror
)
git rev-parse --verify HEAD >nul 2>nul
if errorlevel 1 goto :nocommit
rem Check all newly committed content too; this script never amends historical commits.
echo.
echo [7/7] FINAL PUBLIC UPLOAD CONFIRMATION
echo Destination: %DEST%
echo Source branch: HEAD
choice /C YN /M "PUSH NOW to public GitHub"
if errorlevel 2 goto :cancel
echo.
echo Sending code to GitHub...
git push -u origin HEAD:main
if errorlevel 1 goto :pusherror
echo.
echo =======================================================
echo [SUCCESS] PUSH COMPLETED. Refresh your GitHub page.
echo =======================================================
start "" "https://github.com/SirjohnQC/ai-mastering-lab"
goto :finish
:blocked
echo [STOP] No push. Remove suspicious files from Git staging/history.
echo Existing files on disk have NOT been deleted.
goto :finish
:commiterror
echo [STOP] Commit failed. Check Git user.name and user.email.
goto :finish
:nocommit
echo [STOP] There is no commit to push.
goto :finish
:pusherror
echo [STOP] PUSH FAILED. Check the message immediately above.
echo Verify GitHub login: gh auth status
 echo Or try: git push -u origin HEAD:main
goto :finish
:cancel
echo [CANCELLED] Nothing was pushed.
goto :finish
:nogit
echo [STOP] Git not installed or missing from PATH.
goto :finish
:nopowershell
echo [STOP] PowerShell is required for the safety check.
goto :finish
:error
echo [STOP] A Git command failed; check lines above.
:finish
echo.
echo Save or screenshot any [STOP] message if it still fails.
pause
endlocal
