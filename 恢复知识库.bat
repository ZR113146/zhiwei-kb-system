@echo off
chcp 65001 >nul
REM 备份源目录：可用环境变量 KB_BACKUP_SRC 覆盖，默认 D:\Codex_知识库备份
if "%KB_BACKUP_SRC%"=="" set KB_BACKUP_SRC=D:\Codex_知识库备份
echo ============================================
echo   知微知识库恢复脚本
echo   备份源: %KB_BACKUP_SRC%
echo ============================================
echo.

for /f "tokens=2 delims==" %%I in (
'
wmic os get localdatetime /value ^| find "="
'
) do set datetime=%%I
set TODAY=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%
set WORKDIR=%USERPROFILE%\Documents\Codex\%TODAY%\zhiwei-kb-restore

echo 目标路径: %WORKDIR%
echo.

if not exist "%KB_BACKUP_SRC%\kb_loader.py" (
    echo [错误] 备份源不完整
    pause
    exit /b 1
)

echo [1/3] 创建工作目录...
if not exist "%WORKDIR%" mkdir "%WORKDIR%"

echo [2/3] 拷贝项目文件...
xcopy "%KB_BACKUP_SRC%\*" "%WORKDIR%\" /E /I /H /Y /Q
echo     完成

echo [3/3] 验证...
if exist "%WORKDIR%\kb_loader.py" (echo      kb_loader.py [OK]) else (echo      kb_loader.py [缺失!])
if exist "%WORKDIR%\kb_core\kb.json" (echo      kb_core\kb.json [OK]) else (echo      kb_core\kb.json [缺失!])
if exist "%WORKDIR%\data\vectordb\vectors.npy" (echo      vectors.npy [OK]) else (echo      vectors.npy [缺失!])

echo.
echo ============================================
echo   恢复完成
echo   项目路径: %WORKDIR%
echo ============================================
pause
