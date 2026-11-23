"""Health check (endpoint 25, D38, D62). Não tem service: usa o núcleo (banco.py, D52-1).

O balanceador da produção de referência consulta esta rota (Figura 11): 200
quando a API e o MySQL respondem; 503 BANCO_INDISPONIVEL quando o banco não responde.
"""

import logging

from fastapi import APIRouter, Request
from sqlalchemy.exc import SQLAlchemyError

from app.nucleo.banco import testar_conexao
from app.nucleo.erros import ErroDominio
from app.views.comum import Saude, respostas_erro

log = logging.getLogger("raizes")

router = APIRouter(tags=["Operação"])


@router.get(
    "/health",
    summary="Health check com teste do MySQL (RNF10, D38)",
    response_model=Saude,
    response_description="API e banco disponíveis",
    responses=respostas_erro(503),
)
def health(request: Request) -> Saude:
    try:
        testar_conexao(request.app.state.config)
    except SQLAlchemyError as exc:
        log.error("health check: banco indisponível: %s", exc)
        raise ErroDominio("BANCO_INDISPONIVEL", "Banco de dados indisponível") from None
    return Saude(status="ok", banco="ok")
