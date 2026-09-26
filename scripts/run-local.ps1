# SUMP v2 本地开发：一键启动服务（settings-center + memory + agentloop）
# 用法：.\scripts\run-local.ps1 [-CenterAddr 127.0.0.1:9000] [-MemoryAddr 127.0.0.1:9201] [-AgentAddr 127.0.0.1:9101] [-LlmKey sk-...] [-LlmModel deepseek-chat]
# 停止：Ctrl+C（脚本会清理子进程）
param(
    [string]$CenterAddr = '127.0.0.1:9000',
    [string]$MemoryAddr = '127.0.0.1:9201',
    [string]$AgentAddr = '127.0.0.1:9101',
    [string]$LlmBase = 'https://api.deepseek.com',
    [string]$LlmKey = $env:DEEPSEEK_API_KEY,
    [string]$LlmModel = 'deepseek-chat'
)

$ErrorActionPreference = 'Stop'

$root   = Split-Path -Parent $PSScriptRoot
$binDir = Join-Path $env:TEMP 'sump-v2-bin'
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

function Wait-Port([string]$Addr, [int]$TimeoutSec) {
    $h, $p = $Addr.Split(':')
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $client.Connect($h, [int]$p)
            $client.Close()
            return $true
        } catch {
            Start-Sleep -Milliseconds 300
        }
    }
    return $false
}

Write-Host '[1/4] 构建 settings-center / memory / agentloop ...' -ForegroundColor Cyan
Push-Location $root
try {
    go build -o (Join-Path $binDir 'settings-center.exe') 'github.com/QAQ-awa-QAQ/sump/settings-center'
    if ($LASTEXITCODE -ne 0) { throw 'settings-center 构建失败' }
    go build -o (Join-Path $binDir 'memory.exe') 'github.com/QAQ-awa-QAQ/sump/memory'
    if ($LASTEXITCODE -ne 0) { throw 'memory 构建失败' }
    go build -o (Join-Path $binDir 'agentloop.exe') 'github.com/QAQ-awa-QAQ/sump/agentloop'
    if ($LASTEXITCODE -ne 0) { throw 'agentloop 构建失败' }
} finally {
    Pop-Location
}

$center = $null
$mem    = $null
$agent  = $null
try {
    Write-Host '[2/4] 启动 settings-center ...' -ForegroundColor Cyan
    $center = Start-Process -FilePath (Join-Path $binDir 'settings-center.exe') -ArgumentList '-addr', $CenterAddr -PassThru -NoNewWindow
    if (-not (Wait-Port $CenterAddr 60)) { throw 'settings-center 未在 60 秒内就绪' }

    Write-Host '[3/4] 启动 memory ...' -ForegroundColor Cyan
    $dataDir = Join-Path $root 'data'
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    $mem = Start-Process -FilePath (Join-Path $binDir 'memory.exe') -ArgumentList '-addr', $MemoryAddr, '-center', "ws://$CenterAddr/ws", '-db', (Join-Path $dataDir 'memory.db') -PassThru -NoNewWindow
    if (-not (Wait-Port $MemoryAddr 60)) { throw 'memory 未在 60 秒内就绪' }

    Write-Host '[4/4] 启动 agentloop ...' -ForegroundColor Cyan
    $agentArgs = @('-addr', $AgentAddr, '-center', "ws://$CenterAddr/ws", '-llm-base', $LlmBase, '-llm-model', $LlmModel)
    if ($LlmKey) { $agentArgs += @('-llm-key', $LlmKey) }
    $agent = Start-Process -FilePath (Join-Path $binDir 'agentloop.exe') -ArgumentList $agentArgs -PassThru -NoNewWindow

    Write-Host ''
    Write-Host "settings-center: ws://$CenterAddr/ws  (PID $($center.Id))"
    Write-Host "memory:          ws://$MemoryAddr/ws  (PID $($mem.Id))  db: data/memory.db"
    Write-Host "agentloop:       ws://$AgentAddr/ws  (PID $($agent.Id))"
    Write-Host '按 Ctrl+C 停止' -ForegroundColor Yellow

    Wait-Process -Id $center.Id, $mem.Id, $agent.Id
} finally {
    foreach ($proc in @($center, $mem, $agent)) {
        if ($null -ne $proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
