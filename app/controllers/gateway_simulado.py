"""Rotas do gateway simulado (endpoints 26–28, D39, D44). Service: GatewaySimuladoService (E13).

Este router só é incluído na aplicação quando GATEWAY_SIMULADO=true. Todas as
rotas exigem a ``X-Api-Key`` (GATEWAY_CHAVE_API). Os eventos que o gateway
gera (aprovação, recusa, estorno) são entregues ao webhook da API depois da
resposta, em segundo plano, como um gateway real faria por HTTP (D72).
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status

from app.controllers.pagamentos import entregar_webhook
from app.controllers.parametros import Sessao
from app.nucleo.seguranca import exigir_chave_api
from app.services.gateway_simulado import GatewaySimuladoService
from app.views.comum import respostas_erro
from app.views.gateway_simulado import (
    Cobranca,
    CobrancaEntrada,
    EstornoEntrada,
    ResultadoCobrancaEntrada,
)

router = APIRouter(
    prefix="/gateway-simulado",
    tags=["Gateway simulado"],
    dependencies=[Depends(exigir_chave_api)],
)


def _gateway(request: Request) -> GatewaySimuladoService:
    return request.app.state.gateway_simulado


@router.post(
    "/cobrancas",
    summary="Criar cobrança; mesma referência devolve a mesma transação (D39)",
    status_code=status.HTTP_201_CREATED,
    response_model=Cobranca,
    responses={
        200: {"model": Cobranca, "description": "Referência já existente; mesma transação"},
        **respostas_erro(401, 422),
    },
)
def criar_cobranca(dados: CobrancaEntrada, request: Request, response: Response) -> Cobranca:
    cobranca, criada = _gateway(request).criar_cobranca(dados.referencia, dados.valor, dados.forma)
    if not criada:
        response.status_code = status.HTTP_200_OK
    return Cobranca(transacao_id=cobranca.transacao_id, referencia=cobranca.referencia, status=cobranca.status)


@router.post(
    "/cobrancas/{transacao_id}/resultado",
    summary="Decidir a cobrança e disparar o webhook (uso em testes)",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    response_description="Webhook agendado",
    responses=respostas_erro(401, 404, 409, 422),
)
def decidir_cobranca(
    transacao_id: str, dados: ResultadoCobrancaEntrada, request: Request, sessao: Sessao, tarefas: BackgroundTasks
) -> None:
    evento = _gateway(request).decidir(transacao_id, dados.resultado, dados.motivo)
    tarefas.add_task(entregar_webhook, request.app, sessao, evento)


@router.post(
    "/estornos",
    summary="Solicitar estorno; o resultado chega como refund.completed (UC13)",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    response_description="Estorno aceito",
    responses=respostas_erro(401, 404, 409, 422),
)
def solicitar_estorno(dados: EstornoEntrada, request: Request, sessao: Sessao, tarefas: BackgroundTasks) -> None:
    evento = _gateway(request).estornar(dados.transacao_id)
    tarefas.add_task(entregar_webhook, request.app, sessao, evento)
