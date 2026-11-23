"""Rotas do domínio Pagamentos (endpoints 17–19). Service: PagamentoService (E13).

O controller só valida o formato (view) e chama o service (D32, D50). O que vai
ao gateway depois do COMMIT (estorno, D33) e a entrega dos eventos do gateway
simulado ao webhook (D72) rodam em segundo plano, com ``BackgroundTasks`` do
FastAPI, depois que a resposta sai.

Nas tarefas em segundo plano, a sessão da requisição é reaproveitada: o
SQLAlchemy permite usar a ``Session`` de novo depois do ``close()``, e cada
service termina com COMMIT ou ROLLBACK, o que devolve a conexão ao pool. Nos
testes, isso mantém tudo dentro da transação desfeita no fim (D64).
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, FastAPI, Request, Response, status
from sqlalchemy.orm import Session

from app.controllers.parametros import CORPO_ASSINADO, IP, SO_ATENDENTE, TOKEN, Id, Sessao
from app.nucleo.erros import ErroDominio
from app.nucleo.seguranca import conferir_assinatura
from app.services.gateway_simulado import EventoAssinado
from app.services.pagamentos import PagamentoService
from app.views.comum import respostas_erro
from app.views.pagamentos import (
    EventoWebhook,
    Pagamento,
    PagamentoBalcaoEntrada,
    PagamentoOnlineEntrada,
    ResultadoWebhook,
)

log = logging.getLogger("raizes")

router = APIRouter(tags=["Pagamentos"])


def _service(app: FastAPI, sessao: Session) -> PagamentoService:
    return PagamentoService(sessao, app.state.relogio, app.state.cliente_gateway)


# ---- Tarefas em segundo plano (D33, D72) ----

def pedir_estornos(app: FastAPI, sessao: Session, transacoes: list[str]) -> None:
    """Pede ao gateway o estorno de cada transação, depois do COMMIT (D33)."""
    for transacao in transacoes:
        try:
            evento = app.state.cliente_gateway.solicitar_estorno(transacao)
        except Exception:  # o pagamento fica ESTORNO_SOLICITADO e pode ser pedido de novo
            log.exception("falha ao pedir estorno ao gateway, transacao=%s", transacao)
            continue
        entregar_webhook(app, sessao, evento)  # simulado: o refund.completed chega logo


def entregar_webhook(app: FastAPI, sessao: Session, evento: EventoAssinado) -> None:
    """Gateway simulado (D72): faz o mesmo caminho do POST /webhooks/pagamentos, sem HTTP.

    Confere o HMAC, valida o corpo com a mesma view e chama o mesmo service. Uma
    falha vai só para o log, como um webhook que o gateway real reenviaria.
    """
    try:
        conferir_assinatura(evento.corpo, evento.assinatura, app.state.config.webhook_segredo)
        dados = EventoWebhook.model_validate_json(evento.corpo)
        servico = _service(app, sessao)
        servico.processar_webhook(dados, json.loads(evento.corpo))
    except ErroDominio as erro:  # ex.: TRANSACAO_DESCONHECIDA, cobrança criada fora da API
        sessao.rollback()
        log.warning("webhook do gateway simulado recusado: %s %s", erro.codigo, erro.mensagem)
        return
    except Exception:
        sessao.rollback()
        log.exception("falha ao entregar o webhook do gateway simulado")
        return
    pedir_estornos(app, sessao, servico.estornos)  # aprovação tardia (D24)


# ---- Rotas ----

@router.post(
    "/pedidos/{id}/pagamentos",
    summary="Solicitar pagamento online ao gateway — dono do pedido (RF13, UC06)",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Pagamento,
    response_description="Cobrança aceita pelo gateway; resultado virá pelo webhook",
    responses={
        200: {"model": Pagamento, "description": "Pagamento já solicitado; devolve o mesmo (idempotente)"},
        **respostas_erro(401, 404, 409, 422, 503),
    },
)
def solicitar_pagamento(
    id: Id, dados: PagamentoOnlineEntrada, ator: TOKEN, request: Request, response: Response, sessao: Sessao
) -> Pagamento:
    pagamento, criado = _service(request.app, sessao).solicitar_online(ator, id, dados)
    if not criado:
        response.status_code = status.HTTP_200_OK
    return pagamento


@router.post(
    "/pedidos/{id}/pagamentos/balcao",
    summary="Confirmar pagamento presencial — ATENDENTE da unidade (RF14, UC09, D14)",
    status_code=status.HTTP_201_CREATED,
    response_model=Pagamento,
    responses=respostas_erro(401, 403, 404, 409, 422),
)
def confirmar_pagamento_balcao(
    id: Id, dados: PagamentoBalcaoEntrada, ator: SO_ATENDENTE, ip: IP, request: Request, sessao: Sessao
) -> Pagamento:
    return _service(request.app, sessao).confirmar_balcao(ator, id, dados, ip)


@router.post(
    "/webhooks/pagamentos",
    summary="Receber resultado do gateway (RF14, RF15, RF17, UC07, UC08)",
    response_model=ResultadoWebhook,
    responses=respostas_erro(401, 404, 422),
)
def receber_webhook(
    evento: EventoWebhook, corpo: CORPO_ASSINADO, request: Request, sessao: Sessao, tarefas: BackgroundTasks
) -> ResultadoWebhook:
    # O HMAC já foi conferido sobre o corpo bruto (CORPO_ASSINADO), antes desta linha
    servico = _service(request.app, sessao)
    resultado = servico.processar_webhook(evento, json.loads(corpo))
    if servico.estornos:  # aprovação tardia (D24): estorno depois do COMMIT (D33)
        tarefas.add_task(pedir_estornos, request.app, sessao, list(servico.estornos))
    return resultado
