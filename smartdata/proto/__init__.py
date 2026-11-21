"""Mensagens protobuf do protocolo Xiaomi.

Gerado a partir de defs/ (arquivos .proto do Gadgetbridge, AGPL-3.0) com:
    python -m grpc_tools.protoc -I smartdata/proto/defs --python_out=smartdata/proto \
        smartdata/proto/defs/xiaomi.proto smartdata/proto/defs/xiaomi/*.proto
"""

import sys
from pathlib import Path

# Os módulos gerados fazem "from xiaomi import ...", então esta pasta precisa estar no path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from xiaomi_pb2 import Command  # noqa: E402

__all__ = ["Command"]
