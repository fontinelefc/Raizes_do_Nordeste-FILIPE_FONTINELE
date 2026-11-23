"""Rotas do domínio Fidelidade e LGPD (endpoints 20–24). Service: FidelidadeService (E14).

As rotas usam /clientes/me, sem id, para o cliente só ver os próprios dados (D42).
Só aceitam token de CLIENTE; outro tipo de token responde 401 (D75). O controller
só valida o formato (view) e chama o service (D32, D50); o IP vai para a
auditoria (RF25).
"""

from fastapi import APIRouter, Response, status

from app.controllers.parametros import IP, SO_CLIENTE, Limit, Offset, Sessao
from app.models.enums import Finalidade
from app.services.fidelidade import FidelidadeService
from app.views.acesso import Cliente
from app.views.comum import respostas_erro
from app.views.fidelidade import Consentimento, ConsentimentoEntrada, ListaMovimentacoes

router = APIRouter(tags=["Fidelidade e LGPD"])


@router.get(
    "/clientes/me",
    summary="Dados do cliente e saldo de pontos — CLIENTE (RF17, RF25)",
    response_model=Cliente,
    response_description="Dados do titular (acesso auditado)",
    responses=respostas_erro(401),
)
def dados_cliente(ator: SO_CLIENTE, ip: IP, sessao: Sessao) -> Cliente:
    return FidelidadeService(sessao).dados_cliente(ator, ip)


@router.get(
    "/clientes/me/pontos",
    summary="Extrato de pontos — CLIENTE (RF17, UC08)",
    response_model=ListaMovimentacoes,
    responses=respostas_erro(401),
)
def extrato_pontos(ator: SO_CLIENTE, sessao: Sessao, limit: Limit = 20, offset: Offset = 0) -> ListaMovimentacoes:
    return FidelidadeService(sessao).extrato(ator, limit, offset)


@router.get(
    "/clientes/me/consentimentos",
    summary="Listar consentimentos — CLIENTE (RF20, UC21)",
    response_model=list[Consentimento],
    responses=respostas_erro(401),
)
def listar_consentimentos(ator: SO_CLIENTE, ip: IP, sessao: Sessao) -> list[Consentimento]:
    return FidelidadeService(sessao).listar_consentimentos(ator, ip)


@router.post(
    "/clientes/me/consentimentos",
    summary="Conceder consentimento — CLIENTE (RF20, UC21)",
    status_code=status.HTTP_201_CREATED,
    response_model=Consentimento,
    responses=respostas_erro(401, 409, 422),
)
def conceder_consentimento(dados: ConsentimentoEntrada, ator: SO_CLIENTE, ip: IP, sessao: Sessao) -> Consentimento:
    return FidelidadeService(sessao).conceder_consentimento(ator, dados, ip)


@router.delete(
    "/clientes/me/consentimentos/{finalidade}",
    summary="Revogar consentimento — CLIENTE (RF20, UC21)",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_description="Consentimento revogado (revogado_em preenchido)",
    responses=respostas_erro(401, 404),
)
def revogar_consentimento(finalidade: Finalidade, ator: SO_CLIENTE, ip: IP, sessao: Sessao) -> Response:
    FidelidadeService(sessao).revogar_consentimento(ator, finalidade, ip)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
