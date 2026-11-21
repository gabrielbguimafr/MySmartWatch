"""Cliente do Redmi Watch 2 Lite: conexão, handshake e comandos.

Características do serviço fe95 (XiaomiUuids.java, conjunto V1 criptografado):
  0051 -> comandos vindos do relógio
  0052 -> comandos enviados ao relógio (e os acks deles)
  0053 -> dados de atividade
  0055 -> upload de dados (firmware, mostradores)
"""

import asyncio

from bleak import BleakClient, BleakScanner

from smartdata.proto import Command
from smartdata.proto.xiaomi import wear_account_pb2 as conta_pb

from .atividade import IdArquivo, Montador, ids_de_lista
from .canal import Canal
from .sessao import Sessao


def _uuid(curto: str) -> str:
    return f"0000{curto}-0000-1000-8000-00805f9b34fb"


UUID_CMD_LEITURA = _uuid("0051")
UUID_CMD_ESCRITA = _uuid("0052")
UUID_ATIVIDADE = _uuid("0053")
UUID_UPLOAD = _uuid("0055")

TIPO_AUTH, AUTH_NONCE, AUTH_CONFIRMA = 1, 26, 27
TIPO_SISTEMA, SIS_BATERIA, SIS_INFO = 2, 1, 2
TIPO_SAUDE, SAU_HOJE, SAU_PASSADO, SAU_PEDIR_ARQUIVO = 8, 1, 2, 3
# SAU_ACK = 5 apagaria o arquivo do relógio; NÃO usamos, para o Mi Fitness continuar recebendo tudo.


class Relogio:
    def __init__(self, mac: str, auth_key_hex: str, verbose: bool = False):
        self.mac = mac
        self.sessao = Sessao(auth_key_hex)
        self.verbose = verbose
        self.cliente: BleakClient | None = None
        self.respostas: asyncio.Queue[Command] = asyncio.Queue()
        self.ao_receber_atividade = None  # callback(bytes) para o canal 0053

    # ---------- conexão ----------

    async def conectar(self) -> None:
        dispositivo = await BleakScanner.find_device_by_address(self.mac, timeout=30)
        if not dispositivo:
            raise ConnectionError("Relógio não encontrado (ainda conectado ao celular? longe do PC?).")
        self.cliente = BleakClient(dispositivo, timeout=30)
        await self.cliente.connect()
        # No Windows a negociação de MTU termina pouco depois do connect(); antes disso
        # mtu_size vale 23 e as mensagens seriam picadas em pedaços minúsculos.
        for _ in range(30):
            if (self.cliente.mtu_size or 0) > 23:
                break
            await asyncio.sleep(0.1)
        mtu = self.cliente.mtu_size or 23
        if mtu <= 23:
            print("aviso: MTU continua 23; as mensagens irão em pedaços pequenos")
        if self.verbose:
            print(f"conectado a {dispositivo.name}, MTU={mtu}")

        self.leitura = Canal(self.cliente, UUID_CMD_LEITURA, self.sessao, self._ao_receber_comando, mtu)
        self.escrita = Canal(self.cliente, UUID_CMD_ESCRITA, self.sessao, self._ao_receber_comando, mtu)
        self.atividade = Canal(self.cliente, UUID_ATIVIDADE, self.sessao, self._ao_receber_atividade, mtu)
        self.canais = [self.leitura, self.escrita, self.atividade]
        for canal in self.canais:
            await self.cliente.start_notify(canal.uuid, canal.notificacao)

        await self._autenticar()

    async def desconectar(self) -> None:
        if self.cliente and self.cliente.is_connected:
            await self.cliente.disconnect()

    async def __aenter__(self):
        await self.conectar()
        return self

    async def __aexit__(self, *_):
        await self.desconectar()

    # ---------- mensagens ----------

    def _ao_receber_comando(self, dados: bytes) -> None:
        cmd = Command()
        cmd.ParseFromString(dados)
        if self.verbose:
            print(f"<- tipo={cmd.type} subtipo={cmd.subtype}")
        self.respostas.put_nowait(cmd)

    def _ao_receber_atividade(self, dados: bytes) -> None:
        if self.ao_receber_atividade:
            self.ao_receber_atividade(dados)

    async def enviar(self, cmd: Command) -> None:
        if self.verbose:
            print(f"-> tipo={cmd.type} subtipo={cmd.subtype}")
        await self.escrita.enviar(cmd.SerializeToString())

    async def esperar(self, tipo: int, subtipo: int, timeout: float = 15) -> Command:
        """Espera a resposta (tipo, subtipo); mensagens espontâneas no meio são ignoradas."""
        prazo = asyncio.get_running_loop().time() + timeout
        while True:
            restante = prazo - asyncio.get_running_loop().time()
            if restante <= 0:
                raise TimeoutError(f"Sem resposta para tipo={tipo} subtipo={subtipo}.")
            cmd = await asyncio.wait_for(self.respostas.get(), restante)
            if cmd.type == tipo and cmd.subtype == subtipo:
                return cmd
            if self.verbose:
                print(f"   (ignorado: tipo={cmd.type} subtipo={cmd.subtype})")

    async def pedir(self, tipo: int, subtipo: int, timeout: float = 15) -> Command:
        await self.enviar(Command(type=tipo, subtype=subtipo))
        return await self.esperar(tipo, subtipo, timeout)

    # ---------- handshake ----------

    async def _autenticar(self) -> None:
        passo1 = Command(type=TIPO_AUTH, subtype=AUTH_NONCE)
        passo1.auth.appVerify.nonce = self.sessao.nonce_pc
        await self.enviar(passo1)

        resposta = await self.esperar(TIPO_AUTH, AUTH_NONCE)
        verif = resposta.auth.deviceVerify
        prova = self.sessao.processar_nonce_relogio(verif.nonce, verif.hmac)

        info = conta_pb.CompanionDevice(unknown1=0, phoneApiLevel=34, phoneName="smartData PC",
                                        unknown3=224, region="BR")
        passo2 = Command(type=TIPO_AUTH, subtype=AUTH_CONFIRMA)
        passo2.auth.appConfirm.encryptedNonces = prova
        passo2.auth.appConfirm.encryptedDeviceInfo = self.sessao.cifrar(info.SerializeToString(), 0)
        await self.enviar(passo2)

        await self.esperar(TIPO_AUTH, AUTH_CONFIRMA)
        self.sessao.pronta = True
        for canal in self.canais:
            canal.reset()
        if self.verbose:
            print("autenticado; comunicação cifrada daqui em diante")

    # ---------- comandos simples ----------

    async def bateria(self):
        return (await self.pedir(TIPO_SISTEMA, SIS_BATERIA)).system.power.battery

    async def info(self):
        return (await self.pedir(TIPO_SISTEMA, SIS_INFO)).system.deviceInfo

    # ---------- arquivos de atividade ----------

    async def listar_arquivos(self) -> list[IdArquivo]:
        """IDs dos arquivos de atividade guardados no relógio (de hoje e do passado)."""
        hoje = Command(type=TIPO_SAUDE, subtype=SAU_HOJE)
        hoje.health.activitySyncRequestToday.unknown1 = 0
        await self.enviar(hoje)
        ids = ids_de_lista((await self.esperar(TIPO_SAUDE, SAU_HOJE)).health.activityRequestFileIds)
        passado = await self.pedir(TIPO_SAUDE, SAU_PASSADO)
        ids += ids_de_lista(passado.health.activityRequestFileIds)
        return sorted(set(ids))

    async def baixar_arquivo(self, id_arquivo: IdArquivo, timeout: float = 20) -> bytes:
        """Pede um arquivo e espera ele chegar inteiro pelo canal 0053. Não apaga nada do relógio."""
        montador = Montador()
        pronto: asyncio.Future = asyncio.get_running_loop().create_future()

        def ao_receber(pedaco: bytes) -> None:
            try:
                dados = montador.adicionar(pedaco)
            except ValueError as erro:
                if not pronto.done():
                    pronto.set_exception(erro)
                return
            if dados is not None and not pronto.done():
                pronto.set_result(dados)

        self.ao_receber_atividade = ao_receber
        try:
            pedido = Command(type=TIPO_SAUDE, subtype=SAU_PEDIR_ARQUIVO)
            pedido.health.activityRequestFileIds = id_arquivo.para_bytes()
            await self.enviar(pedido)
            dados = await asyncio.wait_for(pronto, timeout)
        finally:
            self.ao_receber_atividade = None
        if dados[:7] != id_arquivo.para_bytes():
            raise ValueError(f"Recebido arquivo diferente do pedido ({IdArquivo.de_bytes(dados)}).")
        return dados
