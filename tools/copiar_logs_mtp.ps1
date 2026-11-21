# Copia os logs do Mi Fitness do celular (conectado por cabo, modo "Transferência de arquivos")
# para .dados\mifitness_logs, via MTP (não precisa de ADB nem de depuração USB).
# Uso: powershell -ExecutionPolicy Bypass -File tools\copiar_logs_mtp.ps1

$raiz = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $raiz '.dados\mifitness_logs'
$caminho = 'Android', 'data', 'com.xiaomi.wearable', 'files', 'log'

$sh = New-Object -ComObject Shell.Application
$telefone = $sh.NameSpace(17).Items() | Where-Object { $_.Type -match 'Telefone|Phone|Celular|Portátil|Portable' } |
    Select-Object -First 1
if (-not $telefone) { Write-Error 'Celular não encontrado. Conecte o cabo e escolha "Transferência de arquivos".'; exit 1 }

# com a tela bloqueada o armazenamento some; espera até 90 s o usuário desbloquear
$armazenamento = $null
for ($k = 0; $k -lt 45 -and -not $armazenamento; $k++) {
    # busca o aparelho de novo a cada tentativa: o objeto antigo não enxerga o desbloqueio
    $telefone = $sh.NameSpace(17).Items() | Where-Object { $_.Type -match 'Telefone|Phone|Celular|Portátil|Portable' } |
        Select-Object -First 1
    if ($telefone) { $armazenamento = $telefone.GetFolder.Items() | Select-Object -First 1 }
    if (-not $armazenamento) {
        if ($k -eq 0) { Write-Output 'Aguardando acesso aos arquivos: desbloqueie o celular...' }
        Start-Sleep -Seconds 2
    }
}
if (-not $armazenamento) {
    Write-Error "$($telefone.Name) está conectado, mas sem acesso aos arquivos: desbloqueie a tela e, na notificação de USB, escolha 'Transferência de arquivos'."
    exit 1
}
$pasta = $armazenamento.GetFolder
foreach ($p in $caminho) {
    $item = $pasta.Items() | Where-Object { $_.Name -eq $p } | Select-Object -First 1
    if (-not $item) { Write-Error "Pasta '$p' não encontrada no celular."; exit 1 }
    $pasta = $item.GetFolder
}

if (Test-Path $dest) { Remove-Item $dest -Recurse -Force -Confirm:$false }
New-Item -ItemType Directory -Force $dest | Out-Null
$alvo = $sh.NameSpace($dest)
foreach ($i in $pasta.Items()) { $alvo.CopyHere($i, 0x614) }   # sem diálogos, sobrescreve

# CopyHere é assíncrono: espera o tamanho total parar de crescer
$anterior = -1
for ($k = 0; $k -lt 150; $k++) {
    Start-Sleep -Seconds 2
    $soma = (Get-ChildItem $dest -Recurse -File | Measure-Object -Sum Length).Sum
    if ($soma -eq $anterior -and $k -gt 3) { break }
    $anterior = $soma
}
$n = (Get-ChildItem $dest -Recurse -File).Count
Write-Output "Copiados $n arquivo(s), $([math]::Round($anterior / 1MB, 1)) MB, de $($telefone.Name) para $dest"
