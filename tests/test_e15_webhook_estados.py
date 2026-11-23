"""E15 — Webhook: recusa por evento e eventos fora de ordem (RF13, RF14; T3; D27, D43).

Completa o ``test_e13_webhook.py``. Lá, a recusa só era testada pela rota do
gateway simulado. Aqui o evento ``payment.refused`` chega direto pelo webhook,
e também chegam eventos que não combinam com o status atual do pagamento. Esses
eventos ficam registrados e não mudam nada, porque o UPDATE condicional não
encontra o status de origem (D27).
"""

import json

import pytest
from sqlalchemy import text

from app.nucleo.seguranca import assinar
from tests.apoio import MEIO_DIA_RECIFE, codigo, consultar, criar_pedido, estoque, pagar_online

URL = "/api/v1/webhooks/pagamentos"


@pytest.fixture(autouse=True)
def relogio_fixo(api):
    api.app.state.relogio = lambda: MEIO_DIA_RECIFE


def _enviar(api, config, pagamento: dict, tipo: str, status: str, evento_id: str, referencia: str | None = None):
    corpo = json.dumps(
        {
            "evento_id": evento_id,
            "tipo": tipo,
            "transacao_id": pagamento["transacao_gateway"],
            "referencia": referencia or str(pagamento["pedido_id"]),
            "status": status,
            "motivo": "saldo insuficiente" if tipo == "payment.refused" else None,
            "ocorrido_em": "2026-11-23T15:01:00Z",
        }
    ).encode("utf-8")
    cabecalhos = {"Content-Type": "application/json", "X-Assinatura": assinar(corpo, config.webhook_segredo)}
    return api.post(URL, content=corpo, headers=cabecalhos)


def _pedido_com_pagamento(api) -> tuple[dict, dict]:
    pedido = criar_pedido(api)
    pagamento = pagar_online(api, pedido["id"], pedido["token_pedido"])
    assert pagamento.status_code == 202, pagamento.text
    return pedido, pagamento.json()


def _eventos(sessao) -> int:
    return sessao.scalar(text("SELECT COUNT(*) FROM evento_pagamento"))


def test_recusa_pelo_webhook_leva_a_pagamento_recusado_e_libera_a_reserva(api, config, sessao):
    pedido, pagamento = _pedido_com_pagamento(api)
    assert estoque(sessao, 1, 1) == (50, 2)

    resposta = _enviar(api, config, pagamento, "payment.refused", "RECUSADO", "evt_recusa_1")
    assert resposta.status_code == 200 and resposta.json() == {"resultado": "PROCESSADO"}

    detalhe = consultar(api, pedido["id"], pedido["token_pedido"])
    assert detalhe["status"] == "PAGAMENTO_RECUSADO"  # T3
    assert detalhe["pagamento"]["status"] == "RECUSADO"
    assert detalhe["pagamento"]["motivo_recusa"] == "saldo insuficiente"
    assert estoque(sessao, 1, 1) == (50, 0)  # reserva liberada, sem baixa


def test_aprovacao_depois_da_recusa_fica_registrada_sem_efeito(api, config, sessao):
    pedido, pagamento = _pedido_com_pagamento(api)
    _enviar(api, config, pagamento, "payment.refused", "RECUSADO", "evt_recusa_2")

    resposta = _enviar(api, config, pagamento, "payment.approved", "APROVADO", "evt_aprova_2")
    assert resposta.status_code == 200 and resposta.json() == {"resultado": "PROCESSADO"}

    detalhe = consultar(api, pedido["id"], pedido["token_pedido"])
    assert detalhe["status"] == "PAGAMENTO_RECUSADO"  # estado final não volta (D31)
    assert detalhe["pagamento"]["status"] == "RECUSADO"
    assert estoque(sessao, 1, 1) == (50, 0)  # nenhuma baixa
    assert _eventos(sessao) == 2


def test_estorno_concluido_sem_estorno_pedido_nao_muda_o_pagamento(api, config, sessao):
    pedido, pagamento = _pedido_com_pagamento(api)

    resposta = _enviar(api, config, pagamento, "refund.completed", "ESTORNADO", "evt_estorno_3")
    assert resposta.status_code == 200 and resposta.json() == {"resultado": "PROCESSADO"}

    detalhe = consultar(api, pedido["id"], pedido["token_pedido"])
    assert detalhe["status"] == "AGUARDANDO_PAGAMENTO"
    assert detalhe["pagamento"]["status"] == "PENDENTE"  # só ESTORNO_SOLICITADO → ESTORNADO
    assert estoque(sessao, 1, 1) == (50, 2)
    assert _eventos(sessao) == 1


def test_transacao_de_outro_pedido_na_referencia_da_404(api, config, sessao):
    _, pagamento = _pedido_com_pagamento(api)
    resposta = _enviar(api, config, pagamento, "payment.approved", "APROVADO", "evt_ref_4", referencia="999999")
    assert resposta.status_code == 404 and codigo(resposta) == "TRANSACAO_DESCONHECIDA"
    assert _eventos(sessao) == 0
