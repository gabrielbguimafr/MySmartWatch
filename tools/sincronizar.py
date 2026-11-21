"""Baixa os arquivos de atividade do relógio para .dados/brutos/ (sem apagar nada do relógio).

Uso (Bluetooth do celular desligado):
    .venv\\Scripts\\python tools\\sincronizar.py            # baixa só o que ainda não existe
    .venv\\Scripts\\python tools\\sincronizar.py --listar   # só lista
"""

import asyncio
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from smartdata.config import ler_env  # noqa: E402
from smartdata.xiaomi.relogio import Relogio  # noqa: E402

PASTA_BRUTOS = RAIZ / ".dados" / "brutos"


async def main() -> None:
    env = ler_env()
    async with Relogio(env["WATCH_MAC"], env["WATCH_AUTH_KEY"]) as relogio:
        bat = await relogio.bateria()
        print(f"Autenticado. Bateria {bat.level}%.")
        ids = await relogio.listar_arquivos()
        print(f"{len(ids)} arquivo(s) no relógio:")
        for i in ids:
            existe = i.caminho(PASTA_BRUTOS).exists()
            print(f"  {i}{'  (já baixado)' if existe else ''}")
        if "--listar" in sys.argv:
            return

        novos = [i for i in ids if not i.caminho(PASTA_BRUTOS).exists()]
        ok = 0
        for n, i in enumerate(novos, 1):
            try:
                dados = await relogio.baixar_arquivo(i)
            except (TimeoutError, ValueError, RuntimeError) as erro:
                print(f"[{n}/{len(novos)}] falhou {i}: {erro!r}")
                continue
            destino = i.caminho(PASTA_BRUTOS)
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(dados)
            ok += 1
            print(f"[{n}/{len(novos)}] {i}: {len(dados)} bytes")
        print(f"Baixados {ok} de {len(novos)} novo(s) em {PASTA_BRUTOS}")


if __name__ == "__main__":
    asyncio.run(main())
