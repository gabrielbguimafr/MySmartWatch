"""Enquadramento de pacotes em uma característica BLE (protocolo V1).

Portado de XiaomiCharacteristicV1.java (Gadgetbridge). Todo pacote começa com
um uint16 little-endian:
  != 0  -> pedaço (chunk) número N de uma mensagem grande
  == 0  -> pacote de controle, seguido de um byte de tipo:
           0 = início de mensagem em pedaços  [cifrado:u8][num_pedaços:u16]
           1 = ack de pedaços                 [subtipo:u8] 0=fim ok, 1=pode enviar, 2=nack, 5=reenviar
           2 = mensagem única                 [flag:u8 1=cifrada 2=aberta][índice:u16 se cifrada no envio][dados]
           3 = ack de mensagem única          [resultado:u8] 0=ok
"""

import asyncio
import math
import struct
from typing import Awaitable, Callable

from bleak import BleakClient

from .sessao import Sessao

ACK_UNICA = bytes([0, 0, 3, 0])
ACK_INICIO_PEDACOS = bytes([0, 0, 1, 1])
ACK_FIM_PEDACOS = bytes([0, 0, 1, 0])


class Canal:
    def __init__(self, cliente: BleakClient, uuid: str, sessao: Sessao,
                 ao_receber: Callable[[bytes], None] | None = None, mtu: int = 247):
        self.cliente = cliente
        self.uuid = uuid
        self.sessao = sessao
        self.ao_receber = ao_receber
        self.max_escrita = mtu - 3  # desconta o cabeçalho ATT
        self.lock = asyncio.Lock()  # uma mensagem enviada por vez
        self.reset()

    def reset(self) -> None:
        self.indice = 1  # o índice 0 é usado pelo próprio handshake
        self.num_pedacos = 0
        self.pedacos: dict[int, bytes] = {}
        self._espera: asyncio.Future | None = None

    async def _escrever(self, dados: bytes) -> None:
        await self.cliente.write_gatt_char(self.uuid, dados, response=False)

    # ---------- recepção ----------

    depurar = False  # True imprime todo pacote bruto recebido

    def notificacao(self, _caracteristica, dados: bytearray) -> None:
        dados = bytes(dados)
        if self.depurar:
            print(f"   [{self.uuid[4:8]}] <= {len(dados):3d}B {dados[:24].hex()}")
        try:
            self._processar(dados)
        except Exception as erro:  # o bleak engole exceções do callback; mostramos aqui
            print(f"   [{self.uuid[4:8]}] erro ao processar pacote {dados[:16].hex()}...: {erro!r}")

    def _processar(self, dados: bytes) -> None:
        (pedaco,) = struct.unpack_from("<H", dados, 0)
        if pedaco != 0:
            self._receber_pedaco(pedaco, dados[2:])
            return

        tipo = dados[2]
        if tipo == 0:  # relógio vai mandar uma mensagem em pedaços
            self.num_pedacos = struct.unpack_from("<H", dados, 4)[0]
            self.pedacos.clear()
            asyncio.create_task(self._escrever(ACK_INICIO_PEDACOS))
        elif tipo == 1:  # resposta do relógio a um envio nosso em pedaços
            self._resolver(("ack_pedacos", dados[3], dados[4:]))
        elif tipo == 2:  # mensagem única
            asyncio.create_task(self._escrever(ACK_UNICA))
            corpo = dados[4:]
            if dados[3] == 1:
                corpo = self.sessao.decifrar(corpo)
            self._entregar(corpo)
        elif tipo == 3:  # ack de mensagem única
            self._resolver(("ack", dados[3], b""))
        else:
            print(f"[{self.uuid[4:8]}] pacote de tipo desconhecido: {dados.hex()}")

    def _receber_pedaco(self, n: int, corpo: bytes) -> None:
        if n > self.num_pedacos:
            return
        self.pedacos[n] = corpo
        if len(self.pedacos) == self.num_pedacos:
            asyncio.create_task(self._escrever(ACK_FIM_PEDACOS))
            mensagem = b"".join(self.pedacos[i] for i in range(1, self.num_pedacos + 1))
            self.num_pedacos = 0
            self.pedacos.clear()
            self._entregar(self.sessao.decifrar(mensagem))  # pedaços são sempre cifrados

    def _entregar(self, corpo: bytes) -> None:
        if self.ao_receber:
            self.ao_receber(corpo)

    def _resolver(self, valor) -> None:
        if self._espera and not self._espera.done():
            self._espera.set_result(valor)

    def _preparar_espera(self) -> asyncio.Future:
        """Cria a espera ANTES de escrever, para não perder um ack que chegue rápido."""
        self._espera = asyncio.get_running_loop().create_future()
        return self._espera

    async def _aguardar(self, espera: asyncio.Future, timeout: float = 10):
        try:
            return await asyncio.wait_for(espera, timeout)
        finally:
            self._espera = None

    # ---------- envio ----------

    async def enviar(self, mensagem: bytes) -> None:
        async with self.lock:
            cifrar = self.sessao.pronta
            if cifrar:
                indice = self.indice
                self.indice += 1
                mensagem = self.sessao.cifrar(mensagem, indice)

            if cifrar and len(mensagem) + 6 > self.max_escrita:
                await self._enviar_em_pedacos(struct.pack("<H", indice) + mensagem)
                return

            cabecalho = bytes([0, 0, 2, 1 if cifrar else 2])
            if cifrar:
                cabecalho += struct.pack("<H", indice)
            espera = self._preparar_espera()
            await self._escrever(cabecalho + mensagem)
            _, resultado, _ = await self._aguardar(espera)
            if resultado != 0:
                raise RuntimeError(f"Relógio recusou a mensagem (nack {resultado}).")

    async def _enviar_em_pedacos(self, corpo: bytes) -> None:
        tamanho = self.max_escrita - 2
        total = math.ceil(len(corpo) / tamanho)
        espera = self._preparar_espera()
        await self._escrever(struct.pack("<HBBH", 0, 0, 1, total))
        _, subtipo, _ = await self._aguardar(espera)
        if subtipo != 1:
            raise RuntimeError(f"Relógio não aceitou o envio em pedaços (subtipo {subtipo}).")
        espera = self._preparar_espera()
        for i in range(total):
            await self._escrever(struct.pack("<H", i + 1) + corpo[i * tamanho:(i + 1) * tamanho])
        _, subtipo, _ = await self._aguardar(espera)
        if subtipo != 0:
            raise RuntimeError(f"Envio em pedaços falhou (subtipo {subtipo}).")
