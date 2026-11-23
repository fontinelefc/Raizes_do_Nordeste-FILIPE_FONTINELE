"""E13 — Webhook de pagamento: HMAC, idempotência e aprovação tardia (RF14; D24, D27, D43).

Aqui o evento é montado e assinado pelo próprio teste e enviado por HTTP ao
``POST /webhooks/pagamentos``, como faria um gateway real. A assinatura usa o
``WEBHOOK_SEGREDO`` da configuração dos testes.
"""

import json

import pytest
from sqlalchemy import text

from app.nucleo.seguranca import assinar
from app.services.pedidos import PedidoService
from tests.apoio import (
    DEPOIS_DO_PRAZO,
    MEIO_DIA_RECIFE,
    codigo,
    consultar,
    criar_pedido,
    decidir,
    estoque,
    pagar_online,
)

URL = "/api/v1/webhooks/pagamentos"


@pytest.fixture(autouse=True)
def relogio_fixo(api):
    api.app.state.relogio = lambda: MEIO_DIA_RECIFE


def _evento(pagamento: dict, tipo="payment.approved", status="APROVADO", evento_id="evt_teste_1") -> bytes:
    dados = {
        "evento_id": evento_id,
        "tipo": tipo,
        "transacao_id": pagamento["transacao_gateway"],
        "referencia": str(pagamento["pedido_id"]),
        "status": status,
        "motivo": None,
        "ocorrido_em": "2026-11-23T15:01:00Z",
    }
    return json.dumps(dados).encode("utf-8")


def _enviar(api, corpo: bytes, assinatura: str | None):
    cabecalhos = {"Content-Type": "application/json"}
    if assinatura is not None:
        cabecalhos["X-Assinatura"] = assinatura
    return api.post(URL, content=corpo, headers=cabecalhos)


def _eventos(sessao) -> int:
    return sessao.scalar(text("SELECT COUNT(*) FROM evento_pagamento"))


def _pedido_com_pagamento(api) -> tuple[dict, dict]:
    pedido = criar_pedido(api)
    return pedido, pagar_online(api, pedido["id"], pedido["token_pedido"]).json()


def test_webhook_assinado_processa_uma_vez_e_o_repetido_responde_repetido(api, config, sessao):
    pedido, pagamento = _pedido_com_pagamento(api)
    corpo = _evento(pagamento)
    assinatura = assinar(corpo, config.webhook_segredo)

    primeiro = _enviar(api, corpo, assinatura)
    assert primeiro.status_code == 200 and primeiro.json() == {"resultado": "PROCESSADO"}
    repetido = _enviar(api, corpo, assinatura)
    assert repetido.status_code == 200 and repetido.json() == {"resultado": "REPETIDO"}  # D43: não 409

    assert _eventos(sessao) == 1
    assert consultar(api, pedido["id"], pedido["token_pedido"])["status"] == "PAGO"
    assert estoque(sessao, 1, 1) == (48, 0)  # baixa feita uma vez só


def test_assinatura_ausente_errada_ou_de_outro_corpo_da_401(api, config, sessao):
    pedido, pagamento = _pedido_com_pagamento(api)
    corpo = _evento(pagamento)
    sem = _enviar(api, corpo, None)
    assert sem.status_code == 401 and codigo(sem) == "ASSINATURA_INVALIDA"
    errada = _enviar(api, corpo, "sha256=" + "0" * 64)
    assert errada.status_code == 401 and codigo(errada) == "ASSINATURA_INVALIDA"
    outro_corpo = _enviar(api, corpo.replace(b"APROVADO", b"RECUSADO"), assinar(corpo, config.webhook_segredo))
    assert outro_corpo.status_code == 401 and codigo(outro_corpo) == "ASSINATURA_INVALIDA"
    assert _eventos(sessao) == 0
    assert consultar(api, pedido["id"], pedido["token_pedido"])["status"] == "AGUARDANDO_PAGAMENTO"


def test_transacao_desconhecida_da_404(api, config):
    _, pagamento = _pedido_com_pagamento(api)
    corpo = _evento({**pagamento, "transacao_gateway": "sim_naoexiste"})
    resposta = _enviar(api, corpo, assinar(corpo, config.webhook_segredo))
    assert resposta.status_code == 404 and codigo(resposta) == "TRANSACAO_DESCONHECIDA"


def test_evento_invalido_com_assinatura_valida_da_422(api, config, sessao):
    _, pagamento = _pedido_com_pagamento(api)
    incompativel = _evento(pagamento, tipo="payment.approved", status="RECUSADO")
    resposta = _enviar(api, incompativel, assinar(incompativel, config.webhook_segredo))
    assert resposta.status_code == 422 and codigo(resposta) == "VALIDACAO"
    sem_campo = json.dumps({"evento_id": "evt_x", "tipo": "payment.approved"}).encode()
    resposta = _enviar(api, sem_campo, assinar(sem_campo, config.webhook_segredo))
    assert resposta.status_code == 422 and codigo(resposta) == "VALIDACAO"
    assert _eventos(sessao) == 0


def test_aprovacao_tardia_de_pedido_expirado_vira_estorno(api, config, sessao):
    """D24: o pedido expirou (T4) antes da aprovação; ele não volta, e o pagamento é estornado."""
    pedido, pagamento = _pedido_com_pagamento(api)
    api.app.state.relogio = lambda: DEPOIS_DO_PRAZO
    assert PedidoService(sessao, config.jwt_segredo, lambda: DEPOIS_DO_PRAZO).expirar_vencidos() == 1
    assert estoque(sessao, 1, 1) == (50, 0)

    decidir(api, config, pagamento["transacao_gateway"], "APROVADO")
    detalhe = consultar(api, pedido["id"], pedido["token_pedido"])
    assert detalhe["status"] == "EXPIRADO"  # não é transição do pedido (D31)
    assert detalhe["pagamento"]["status"] == "ESTORNADO"  # APROVADO → ESTORNO_SOLICITADO → ESTORNADO
    assert estoque(sessao, 1, 1) == (50, 0)  # nenhuma baixa
    assert _eventos(sessao) == 2  # payment.approved e refund.completed
