"""Conecta no relógio (WATCH_MAC do .env) e lista serviços/características GATT.

Só leitura da estrutura: não escreve nada no relógio.
Uso: .venv\\Scripts\\python tools\\servicos_ble.py
"""

import asyncio
import sys
from pathlib import Path

from bleak import BleakClient, BleakScanner

RAIZ = Path(__file__).resolve().parent.parent


def ler_env() -> dict:
    env = {}
    for linha in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in linha:
            k, v = linha.split("=", 1)
            env[k.strip()] = v.strip()
    return env


async def main() -> None:
    mac = ler_env()["WATCH_MAC"]
    print(f"Procurando {mac} (até 30s)...")
    dispositivo = await BleakScanner.find_device_by_address(mac, timeout=30)
    if not dispositivo:
        sys.exit("Relógio não encontrado. Ele está longe, ainda conectado ao celular, ou com a tela apagada há muito tempo.")
    print(f"Achado: {dispositivo.name}. Conectando...")
    async with BleakClient(dispositivo, timeout=30) as cliente:
        print(f"Conectado. MTU={cliente.mtu_size}")
        for servico in cliente.services:
            print(f"\n[Serviço] {servico.uuid}  {servico.description}")
            for c in servico.characteristics:
                print(f"   {c.uuid}  handle={c.handle:<4} {','.join(c.properties):<40} {c.description}")


if __name__ == "__main__":
    asyncio.run(main())
