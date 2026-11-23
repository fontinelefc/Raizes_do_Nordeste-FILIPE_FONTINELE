"""Formato único de erro (D41) e tradução de erros de domínio para HTTP (D52-6).

Toda resposta de erro tem o formato::

    {"erro": {"codigo": "...", "mensagem": "...", "detalhes": [...], "request_id": "..."}}

Os services lançam ``ErroDominio`` sem conhecer HTTP; o status de cada código
fica na tabela ``STATUS_POR_CODIGO``, completada nas etapas E11–E14 conforme os
códigos da seção 3.6.4 forem usados.
"""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

CABECALHO_REQUEST_ID = "X-Request-ID"

log = logging.getLogger("raizes")

STATUS_POR_CODIGO: dict[str, int] = {
    # E09C
    "VALIDACAO": 422,
    "NAO_ENCONTRADO": 404,
    "NAO_IMPLEMENTADO": 501,
    # E11 (seção 3.6.4)
    "NAO_AUTENTICADO": 401,
    "CREDENCIAIS_INVALIDAS": 401,
    "SEM_PERMISSAO": 403,
    "EMAIL_JA_CADASTRADO": 409,
    "CODIGO_JA_CADASTRADO": 409,
    "PRODUTO_INCOMPATIVEL_UNIDADE": 409,
    "PRECO_FORA_DA_FAIXA": 422,
    # E12 (seção 3.6.4)
    "UNIDADE_FECHADA": 409,
    "ITEM_INDISPONIVEL": 409,
    "ESTOQUE_INSUFICIENTE": 409,
    "TRANSICAO_INVALIDA": 409,
    "JUSTIFICATIVA_OBRIGATORIA": 422,
    # E13 (seção 3.6.4)
    "ASSINATURA_INVALIDA": 401,
    "TRANSACAO_DESCONHECIDA": 404,
    "GATEWAY_INDISPONIVEL": 503,
    # E14 (seção 3.6.4)
    "PEDIDO_NAO_PAGAVEL": 409,
    "CONSENTIMENTO_VIGENTE": 409,
    "AUTORIZACAO_RESPONSAVEL_OBRIGATORIA": 422,
    "ERRO_INTERNO": 500,
    "BANCO_INDISPONIVEL": 503,
}


class ErroDominio(Exception):
    def __init__(self, codigo: str, mensagem: str, detalhes: list[dict] | None = None):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem
        self.detalhes = detalhes or []


class NaoImplementado(ErroDominio):
    """Usado pelo esqueleto das rotas (E09C) até cada regra ser implementada."""

    def __init__(self) -> None:
        super().__init__("NAO_IMPLEMENTADO", "Endpoint previsto no contrato, ainda não implementado")


def _corpo(request: Request, codigo: str, mensagem: str, detalhes: list[dict]) -> dict:
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    erro = {"codigo": codigo, "mensagem": mensagem, "request_id": request_id}
    if detalhes:
        erro["detalhes"] = detalhes
    return {"erro": erro}


async def _tratar_dominio(request: Request, exc: ErroDominio) -> JSONResponse:
    status = STATUS_POR_CODIGO.get(exc.codigo, 500)
    return JSONResponse(_corpo(request, exc.codigo, exc.mensagem, exc.detalhes), status_code=status)


async def _tratar_validacao(request: Request, exc: RequestValidationError) -> JSONResponse:
    detalhes = [
        {
            "campo": ".".join(str(parte) for parte in e["loc"][1:]) or str(e["loc"][0]),
            "valor": e.get("input"),
            "problema": e["msg"],
        }
        for e in exc.errors()
    ]
    corpo = _corpo(request, "VALIDACAO", "Dados de entrada inválidos", detalhes)
    return JSONResponse(jsonable_encoder(corpo), status_code=422)


async def _tratar_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    codigo = "NAO_ENCONTRADO" if exc.status_code == 404 else "ERRO_HTTP"
    return JSONResponse(
        _corpo(request, codigo, str(exc.detail), []),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


async def _tratar_banco(request: Request, exc: DBAPIError) -> JSONResponse:
    # Conexão perdida ou recusada: 503 BANCO_INDISPONIVEL; outro erro do banco: 500
    if exc.connection_invalidated or _falha_de_conexao(exc):
        log.error("banco indisponível request_id=%s: %s", request.state.request_id, exc.orig)
        return JSONResponse(
            _corpo(request, "BANCO_INDISPONIVEL", "Banco de dados indisponível", []), status_code=503
        )
    return await _tratar_inesperado(request, exc)


def _falha_de_conexao(exc: DBAPIError) -> bool:
    # 2003: não conectou; 2006/2013: conexão caiu (códigos do cliente MySQL)
    codigo = exc.orig.args[0] if exc.orig is not None and exc.orig.args else None
    return codigo in {2003, 2006, 2013}


async def _tratar_inesperado(request: Request, exc: Exception) -> JSONResponse:
    # 3.6.4: falha não prevista responde 500 sem pilha; o detalhe vai só para o log
    log.exception("erro interno request_id=%s", getattr(request.state, "request_id", None))
    resposta = JSONResponse(_corpo(request, "ERRO_INTERNO", "Erro interno", []), status_code=500)
    if getattr(request.state, "request_id", None):
        resposta.headers[CABECALHO_REQUEST_ID] = request.state.request_id
    return resposta


def registrar_tratadores(app: FastAPI) -> None:
    app.add_exception_handler(ErroDominio, _tratar_dominio)
    app.add_exception_handler(RequestValidationError, _tratar_validacao)
    app.add_exception_handler(StarletteHTTPException, _tratar_http)
    app.add_exception_handler(DBAPIError, _tratar_banco)
    app.add_exception_handler(Exception, _tratar_inesperado)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        # D40: devolve o X-Request-ID recebido ou gera um novo
        request.state.request_id = request.headers.get(CABECALHO_REQUEST_ID) or str(uuid.uuid4())
        resposta = await call_next(request)
        resposta.headers[CABECALHO_REQUEST_ID] = request.state.request_id
        return resposta
