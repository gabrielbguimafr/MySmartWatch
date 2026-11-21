"""Lista dispositivos BLE próximos (procura o Redmi Watch 2 Lite).

Uso: .venv\\Scripts\\python tools\\scan_ble.py [segundos]
"""

import asyncio
import sys

from bleak import BleakScanner


async def main(segundos: float) -> None:
    print(f"Escaneando por {segundos:.0f}s...")
    achados = await BleakScanner.discover(timeout=segundos, return_adv=True)
    linhas = sorted(achados.values(), key=lambda par: par[1].rssi, reverse=True)
    for dispositivo, adv in linhas:
        nome = adv.local_name or dispositivo.name or "?"
        marca = "  <== relógio?" if any(k in nome.lower() for k in ("redmi", "watch", "xiaomi", "mi ")) else ""
        print(f"{dispositivo.address}  rssi={adv.rssi:>4}  {nome}{marca}")
        if marca:
            print(f"    serviços anunciados: {adv.service_uuids}")
            print(f"    dados do fabricante: { {k: v.hex() for k, v in adv.manufacturer_data.items()} }")
    print(f"{len(linhas)} dispositivo(s).")


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 10))
