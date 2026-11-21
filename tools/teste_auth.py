"""Conecta, autentica e lê bateria + informações do relógio.

Uso (com o Bluetooth do celular desligado):
    .venv\\Scripts\\python tools\\teste_auth.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartdata.config import ler_env  # noqa: E402
from smartdata.xiaomi.relogio import Relogio  # noqa: E402


async def main() -> None:
    env = ler_env()
    async with Relogio(env["WATCH_MAC"], env["WATCH_AUTH_KEY"], verbose=True) as relogio:
        info = await relogio.info()
        print(f"\nModelo: {info.model}  firmware: {info.firmware}  serial: ...{info.serialNumber[-4:]}")
        bat = await relogio.bateria()
        print(f"Bateria: {bat.level}%  (estado {bat.state})")


if __name__ == "__main__":
    asyncio.run(main())
