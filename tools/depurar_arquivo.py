"""Pede UM arquivo de atividade e imprime todos os pacotes brutos recebidos (depuração)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartdata.config import ler_env  # noqa: E402
from smartdata.xiaomi.canal import Canal  # noqa: E402
from smartdata.xiaomi.relogio import Relogio  # noqa: E402


async def main() -> None:
    env = ler_env()
    async with Relogio(env["WATCH_MAC"], env["WATCH_AUTH_KEY"], verbose=True) as relogio:
        ids = await relogio.listar_arquivos()
        alvo = ids[-1]
        print(f"\nPedindo {alvo} ({alvo.para_bytes().hex()})")
        Canal.depurar = True
        try:
            dados = await relogio.baixar_arquivo(alvo, timeout=15)
            print(f"OK: {len(dados)} bytes")
        except Exception as erro:
            print(f"Falhou: {erro!r}")
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
