"""Lê o .env do projeto (WATCH_MAC, WATCH_AUTH_KEY)."""

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def ler_env() -> dict[str, str]:
    env = {}
    arquivo = RAIZ / ".env"
    if arquivo.exists():
        # utf-8-sig: tolera o BOM que o PowerShell 5 coloca ao gravar arquivos
        for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                k, v = linha.split("=", 1)
                env[k.strip()] = v.strip()
    return env
