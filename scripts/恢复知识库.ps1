$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
if (-not $env:KB_BACKUP_SRC) { $env:KB_BACKUP_SRC = "D:\Codex_知识库备份" }

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  知微知识库恢复脚本" -ForegroundColor Cyan
Write-Host "  备份源: $env:KB_BACKUP_SRC" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$today = Get-Date -Format "yyyy-MM-dd"
$workdir = "$env:USERPROFILE\Documents\Codex\$today\zhiwei-kb-restore"
Write-Host "目标路径: $workdir" -ForegroundColor Yellow
Write-Host ""

if (-not (Test-Path "$env:KB_BACKUP_SRC\kb_loader.py")) {
    Write-Host "[错误] 备份源不完整" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

Write-Host "[1/3] 创建工作目录..." -ForegroundColor Green
New-Item -ItemType Directory -Path $workdir -Force | Out-Null

Write-Host "[2/3] 拷贝项目文件 (2.97GB)..." -ForegroundColor Green
Copy-Item "$env:KB_BACKUP_SRC\*" -Destination $workdir -Recurse -Force
Write-Host "     项目文件拷贝完成" -ForegroundColor Green

Write-Host "[3/3] 技能定义..." -ForegroundColor Green
Write-Host "     技能由 Codex 平台独立管理，请通过 skill-installer 重新安装" -ForegroundColor Yellow

Write-Host "[3/3] 验证恢复完整性..." -ForegroundColor Green
$allOk = $true

$checks = @(
    @{Name="kb_loader.py"; Path="$workdir\kb_loader.py"},
    @{Name="kb_core\kb.json"; Path="$workdir\kb_core\kb.json"},
    @{Name="kb_core\kb_resolver_core.py"; Path="$workdir\kb_core\kb_resolver_core.py"},
    @{Name="vectors.npy"; Path="$workdir\data\vectordb\vectors.npy"},
    @{Name="metadata.json"; Path="$workdir\data\vectordb\metadata.json"},
    @{Name="kb_search_index.json"; Path="$workdir\data\kb_json\kb_search_index.json"},
    @{Name="kb_vector_search_local.py"; Path="$workdir\pipeline\kb_vector_search_local.py"},
    @{Name="plan_bridge.py"; Path="$workdir\plan_bridge.py"},
    @{Name="codex_word.py"; Path="$workdir\codex_word.py"},
)

foreach ($c in $checks) {
    if (Test-Path $c.Path) {
        Write-Host "     $($c.Name) [OK]" -ForegroundColor Green
    } else {
        Write-Host "     $($c.Name) [缺失!]" -ForegroundColor Red
        $allOk = $false
    }
}

Write-Host ""
if ($allOk) {
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  恢复完成，全部验证通过" -ForegroundColor Green
    Write-Host "  项目路径: $workdir" -ForegroundColor Yellow
    Write-Host "============================================" -ForegroundColor Cyan
} else {
    Write-Host "有文件缺失，请检查备份源" -ForegroundColor Red
}
Read-Host "按 Enter 退出"
