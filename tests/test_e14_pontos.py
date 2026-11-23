"""E14 — Pontos de fidelidade: crédito no T2 e estorno no cancelamento (RF17; RN14, RN16; D69, D74).

Regra (D74): 1 ponto por R$ 1,00, sem os centavos, só para cliente com
consentimento FIDELIDADE vigente. O ``PEDIDO_APP`` custa "43.30": 43 pontos.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services.fidelidade import pontos_do_valor
from tests.apoio import (
    MEIO_DIA_RECIFE,
    auth,
    criar_pedido,
    decidir,
    pagar_online,
    pedido_pago_online,
    saldo,
)

JUSTIFICATIVA = "Cliente desistiu do pedido"
MOVIMENTOS_DO_PEDIDO = text("SELECT COUNT(*) FROM movimentacao_pontos WHERE pedido_id = :id")


@pytest.fixture(autouse=True)
def relogio_fixo(api):
    api.app.state.relogio = lambda: MEIO_DIA_RECIFE


def _extrato(api, token: str) -> dict:
    resposta = api.get("/api/v1/clientes/me/pontos", headers=auth(token))
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _cancelar(api, pedido_id: int, token: str):
    resposta = api.post(
        f"/api/v1/pedidos/{pedido_id}/cancelamento", json={"justificativa": JUSTIFICATIVA}, headers=auth(token)
    )
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


@pytest.mark.parametrize("valor, pontos", [("43.30", 43), ("37.90", 37), ("1.00", 1), ("0.99", 0), ("100.00", 100)])
def test_um_ponto_por_real_sem_os_centavos(valor, pontos):
    assert pontos_do_valor(Decimal(valor)) == pontos


def test_pagamento_aprovado_credita_pontos_ao_cliente_com_consentimento(api, config, sessao, tokens):
    pedido = pedido_pago_online(api, config, tokens["maria"])
    assert saldo(sessao, 1) == 43
    extrato = _extrato(api, tokens["maria"])
    assert extrato["total"] == 1
    assert extrato["itens"][0] | {"id": 0, "criado_em": ""} == {
        "id": 0, "pedido_id": pedido["id"], "tipo": "CREDITO", "pontos": 43, "criado_em": ""
    }
    dados = api.get("/api/v1/clientes/me", headers=auth(tokens["maria"])).json()
    assert dados["saldo_pontos"] == 43


def test_sem_consentimento_vigente_nao_ha_credito(api, config, sessao, tokens):
    """RN16: o João não tem consentimento; a Maria revoga o dela antes de pagar."""
    pedido_pago_online(api, config, tokens["joao"])
    assert saldo(sessao, 2) == 0 and _extrato(api, tokens["joao"])["total"] == 0

    api.delete("/api/v1/clientes/me/consentimentos/FIDELIDADE", headers=auth(tokens["maria"]))
    pedido_pago_online(api, config, tokens["maria"])
    assert saldo(sessao, 1) == 0 and _extrato(api, tokens["maria"])["total"] == 0


def test_pagamento_recusado_e_pedido_anonimo_nao_creditam(api, config, sessao, tokens):
    pedido = criar_pedido(api, token=tokens["maria"])
    pagamento = pagar_online(api, pedido["id"], tokens["maria"]).json()
    decidir(api, config, pagamento["transacao_gateway"], "RECUSADO", "Saldo insuficiente")
    assert saldo(sessao, 1) == 0

    anonimo = criar_pedido(api)
    transacao = pagar_online(api, anonimo["id"], anonimo["token_pedido"]).json()["transacao_gateway"]
    decidir(api, config, transacao, "APROVADO")
    assert sessao.scalar(MOVIMENTOS_DO_PEDIDO, {"id": anonimo["id"]}) == 0


def test_cancelar_pedido_pago_estorna_os_pontos(api, config, sessao, tokens):
    """T9 pelo próprio cliente: o saldo volta a zero e o extrato mostra o estorno."""
    pedido = pedido_pago_online(api, config, tokens["maria"])
    _cancelar(api, pedido["id"], tokens["maria"])
    assert saldo(sessao, 1) == 0
    extrato = _extrato(api, tokens["maria"])
    assert extrato["total"] == 2
    assert [(m["tipo"], m["pontos"]) for m in extrato["itens"]] in (
        [("ESTORNO", -43), ("CREDITO", 43)],  # mais recente primeiro
        [("CREDITO", 43), ("ESTORNO", -43)],  # mesmo segundo: a ordem pelo id decide
    )


def test_cancelar_em_preparo_estorna_mesmo_com_consentimento_revogado(api, config, sessao, tokens):
    """T10 pelo GERENTE: os pontos do pedido voltam, mesmo que o cliente tenha revogado o consentimento depois."""
    pedido = pedido_pago_online(api, config, tokens["maria"])
    assert saldo(sessao, 1) == 43
    api.delete("/api/v1/clientes/me/consentimentos/FIDELIDADE", headers=auth(tokens["maria"]))
    preparo = api.patch(
        f"/api/v1/pedidos/{pedido['id']}/status", json={"status": "EM_PREPARO"}, headers=auth(tokens["cozinha_recife"])
    )
    assert preparo.status_code == 200
    _cancelar(api, pedido["id"], tokens["gerente_recife"])
    assert saldo(sessao, 1) == 0


def test_cancelar_antes_de_pagar_nao_mexe_nos_pontos(api, sessao, tokens):
    pedido = criar_pedido(api, token=tokens["maria"])
    _cancelar(api, pedido["id"], tokens["maria"])  # T5
    assert saldo(sessao, 1) == 0 and sessao.scalar(MOVIMENTOS_DO_PEDIDO, {"id": pedido["id"]}) == 0
