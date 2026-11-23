"""Rotas do domínio Acesso (endpoints 1–2). Service: AcessoService (E11)."""

from fastapi import APIRouter, Request, status

from app.controllers.parametros import Sessao
from app.services.acesso import AcessoService
from app.views.acesso import Cliente, ClienteEntrada, LoginEntrada, Token
from app.views.comum import respostas_erro

router = APIRouter(tags=["Acesso"])


def _service(request: Request, sessao: Sessao) -> AcessoService:
    return AcessoService(sessao, request.app.state.config.jwt_segredo)


@router.post(
    "/auth/login",
    summary="Autenticar funcionário ou cliente (RF01, UC16)",
    response_model=Token,
    responses=respostas_erro(401, 422),
)
def login(dados: LoginEntrada, request: Request, sessao: Sessao) -> Token:
    return _service(request, sessao).login(dados)


@router.post(
    "/clientes",
    summary="Cadastrar cliente (RF01, UC16)",
    status_code=status.HTTP_201_CREATED,
    response_model=Cliente,
    responses=respostas_erro(409, 422),
)
def cadastrar_cliente(dados: ClienteEntrada, request: Request, sessao: Sessao) -> Cliente:
    return _service(request, sessao).cadastrar_cliente(dados)
