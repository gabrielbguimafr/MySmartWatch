"""Extrai a auth key do Redmi Watch 2 Lite dos logs do Mi Fitness via ADB.

Pré-requisitos: celular com Depuração USB ligada, conectado por cabo e autorizado,
e o Mi Fitness tendo sincronizado o relógio recentemente.

Uso: .venv\\Scripts\\python tools\\extrair_chave.py [--local]

Copia os logs para .dados/mifitness_logs/ e grava a chave em .env como
WATCH_AUTH_KEY, mostrando só os últimos 4 caracteres.
"""

import gzip
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_LOGS = RAIZ / ".dados" / "mifitness_logs"
ARQUIVO_ENV = RAIZ / ".env"
CAMINHO_CELULAR = "/sdcard/Android/data/com.xiaomi.wearable/files/log"
PADRAO = re.compile(r"(encryptKey|token|authKey|huamiAuthKey)[\"':= ]+([0-9a-fA-F]{32})")


def achar_adb() -> str:
    adb = shutil.which("adb")
    if adb:
        return adb
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet"
    candidatos = [winget / "Links" / "adb.exe", *winget.glob("Packages/Google.PlatformTools*/platform-tools/adb.exe")]
    for c in candidatos:
        if c.is_file():
            return str(c)
    sys.exit("adb não encontrado. Instale com: winget install Google.PlatformTools")


def textos(arquivo: Path):
    """Gera o conteúdo de texto do arquivo (abre .zip e .gz)."""
    dados = arquivo.read_bytes()
    if zipfile.is_zipfile(arquivo):
        with zipfile.ZipFile(arquivo) as z:
            for nome in z.namelist():
                yield f"{arquivo.name}:{nome}", z.read(nome).decode("utf-8", "ignore")
    elif dados[:2] == b"\x1f\x8b":
        yield arquivo.name, gzip.decompress(dados).decode("utf-8", "ignore")
    else:
        yield arquivo.name, dados.decode("utf-8", "ignore")


def gravar_env(chave: str) -> None:
    linhas = ARQUIVO_ENV.read_text(encoding="utf-8-sig").splitlines() if ARQUIVO_ENV.exists() else []
    linhas = [l for l in linhas if not l.startswith("WATCH_AUTH_KEY=")]
    linhas.append(f"WATCH_AUTH_KEY={chave}")
    ARQUIVO_ENV.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def copiar_via_adb() -> None:
    adb = achar_adb()
    saida = subprocess.run([adb, "devices"], capture_output=True, text=True).stdout
    aparelhos = [l for l in saida.splitlines()[1:] if l.strip()]
    if not aparelhos:
        sys.exit("Nenhum celular conectado. Ligue a Depuração USB e conecte o cabo.")
    if any("unauthorized" in l for l in aparelhos):
        sys.exit("Celular não autorizado: aceite o pedido de depuração USB na tela do celular.")

    if PASTA_LOGS.exists():
        shutil.rmtree(PASTA_LOGS)
    PASTA_LOGS.mkdir(parents=True)
    r = subprocess.run([adb, "pull", CAMINHO_CELULAR, str(PASTA_LOGS)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"Falha ao copiar os logs:\n{r.stderr.strip()}")


def main() -> None:
    # --local: só analisa os logs já copiados (por exemplo via MTP/Explorer) em .dados/mifitness_logs.
    if "--local" in sys.argv:
        if not PASTA_LOGS.is_dir():
            sys.exit(f"Pasta {PASTA_LOGS} não existe.")
    else:
        copiar_via_adb()

    achados = []  # (data de modificação, origem, campo, chave)
    for arquivo in PASTA_LOGS.rglob("*"):
        if arquivo.is_file():
            for origem, texto in textos(arquivo):
                for m in PADRAO.finditer(texto):
                    achados.append((arquivo.stat().st_mtime, origem, m.group(1), m.group(2).lower()))

    if not achados:
        sys.exit("Nenhuma chave nos logs. Sincronize o relógio no Mi Fitness e rode de novo.")

    distintas = {c for *_, c in achados}
    print(f"{len(achados)} ocorrência(s), {len(distintas)} chave(s) distinta(s):")
    for c in distintas:
        n = sum(1 for *_, x in achados if x == c)
        print(f"  ...{c[-4:]}  ({n}x)")

    # Usa a ocorrência mais recente (último arquivo modificado, última linha).
    _, origem, campo, chave = sorted(achados, key=lambda a: a[0])[-1]
    gravar_env(chave)
    print(f"Gravada em .env: WATCH_AUTH_KEY=...{chave[-4:]}  (campo '{campo}' em {origem})")


if __name__ == "__main__":
    main()
