"""Ponto de entrada da API Raízes do Nordeste.

Executar: ``uvicorn app.main:app --reload``  →  Swagger em http://localhost:8000/docs
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from fastapi import FastAPI

from app.controllers import (
    acesso,
    estoque,
    fidelidade,
    gateway_simulado,
    pagamentos,
    pedidos,
    saude,
    unidades,
)
from app.nucleo.cliente_gateway import ClienteGateway
from app.nucleo.config import Config, carregar_config
from app.nucleo.erros import registrar_tratadores
from app.services.gateway_simulado import GatewaySimuladoService, MemoriaGateway

PREFIXO = "/api/v1"

log = logging.getLogger("raizes")

TAGS = [
    {"name": "Acesso"},
    {"name": "Unidades e catálogo"},
    {"name": "Estoque"},
    {"name": "Pedidos"},
    {"name": "Pagamentos"},
    {"name": "Fidelidade e LGPD"},
    {"name": "Operação"},
    {"name": "Gateway simulado"},
]


async def _expirar_periodicamente(app: FastAPI, intervalo: int) -> None:
    """D71: a cada ``intervalo`` segundos, expira os pedidos vencidos (T4) numa thread à parte."""
    while True:
        await asyncio.sleep(intervalo)
        try:
            await asyncio.to_thread(pedidos.expirar_pedidos, app)
        except Exception:  # banco fora do ar, por exemplo: tenta de novo na próxima rodada
            log.exception("falha na tarefa de expiração")


@asynccontextmanager
async def _ciclo_de_vida(app: FastAPI):
    intervalo = app.state.config.expiracao_intervalo
    tarefa = asyncio.create_task(_expirar_periodicamente(app, intervalo)) if intervalo > 0 else None
    yield
    if tarefa is not None:
        tarefa.cancel()
        with suppress(asyncio.CancelledError):
            await tarefa


def criar_app(config: Config | None = None) -> FastAPI:
    config = config or carregar_config()
    app = FastAPI(
        title="API Raízes do Nordeste",
        version="1.0.0",
        description="API REST da rede Raízes do Nordeste",
        openapi_tags=TAGS,
        lifespan=_ciclo_de_vida,
    )
    app.state.config = config  # lida pelo núcleo: banco (D55) e JWT (D42)
    app.state.relogio = lambda: datetime.now(timezone.utc)  # hora atual; os testes fixam (D70)
    # Gateway simulado (D72, D73): memória própria por aplicação; sem ele, o pagamento online responde 503
    gateway = None
    if config.gateway_simulado:
        gateway = GatewaySimuladoService(MemoriaGateway(), config.webhook_segredo, lambda: app.state.relogio())
    app.state.gateway_simulado = gateway
    app.state.cliente_gateway = ClienteGateway(gateway)
    registrar_tratadores(app)

    for modulo in (acesso, unidades, estoque, pedidos, pagamentos, fidelidade, saude):
        app.include_router(modulo.router, prefix=PREFIXO)
    if config.gateway_simulado:  # D44
        app.include_router(gateway_simulado.router, prefix=PREFIXO)
    return app


app = criar_app()
