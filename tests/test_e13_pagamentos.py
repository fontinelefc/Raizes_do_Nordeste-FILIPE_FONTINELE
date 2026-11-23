"""E13 — Pagamento online e no balcão, estorno no cancelamento (RF13, RF14; T2, T3, T9–T11; D14, D39, D69).

O pagamento online passa pelo gateway simulado (D72): a API cria a cobrança, a
rota de teste do gateway decide o resultado, e o evento chega ao webhook em
segundo plano, antes de o ``TestClient`` devolver a resposta. Assim, logo
depois de ``decidir``, o pedido já mudou.

Carga de exemplo: Tapioca (1) em Recife tem 50 unidades e o suco (5), 80. O
``PEDIDO_APP`` leva 2 tapiocas e 1 suco, total "43.30".
"""

import pytest
from sqlalchemy import text

from app.nucleo.cliente_gateway import ClienteGateway
from tests.apoio import (
    DEPOIS_DO_PRAZO,
    MEIO_DIA_RECIFE,
    PEDIDO_APP,
    PEDIDO_BALCAO,
    auth,
    codigo,
    consultar,
    criar_pedido,
    decidir,
    estoque,
    pagar_online,
)

JUSTIFICATIVA = "Cliente desistiu do pedido"


@pytest.fixture(autouse=True)
def relogio_fixo(api):
    api.app.state.relogio = lambda: MEIO_DIA_RECIFE


def _balcao(api, pedido_id: int, token: str, forma: str = "DINHEIRO"):
    return api.post(f"/api/v1/pedidos/{pedido_id}/pagamentos/balcao", json={"forma": forma}, headers=auth(token))


def _cancelar(api, pedido_id: int, token: str):
    return api.post(
        f"/api/v1/pedidos/{pedido_id}/cancelamento", json={"justificativa": JUSTIFICATIVA}, headers=auth(token)
    )


# ---- RF13 / T2: pagamento online aprovado ----

def test_pagamento_online_aprovado_leva_o_pedido_a_pago_com_baixa(api, config, sessao):
    pedido = criar_pedido(api)
    resposta = pagar_online(api, pedido["id"], pedido["token_pedido"])
    assert resposta.status_code == 202
    pagamento = resposta.json()
    assert pagamento["tipo"] == "ONLINE" and pagamento["forma"] == "PIX" and pagamento["status"] == "PENDENTE"
    assert pagamento["valor"] == "43.30"  # valor do pedido, nunca do corpo
    assert pagamento["transacao_gateway"].startswith("sim_")

    de_novo = pagar_online(api, pedido["id"], pedido["token_pedido"], "CARTAO_CREDITO")
    assert de_novo.status_code == 200 and de_novo.json() == pagamento  # idempotente (D39)

    assert decidir(api, config, pagamento["transacao_gateway"], "APROVADO").status_code == 202
    detalhe = consultar(api, pedido["id"], pedido["token_pedido"])
    assert detalhe["status"] == "PAGO" and detalhe["expira_em"] is None
    assert detalhe["pagamento"]["status"] == "APROVADO"
    assert detalhe["historico"][-1] == {"status": "PAGO", "origem": "GATEWAY", "em": "2026-11-23T15:00:00Z"}
    assert estoque(sessao, 1, 1) == (48, 0) and estoque(sessao, 1, 5) == (79, 0)  # reserva virou baixa (D06)


# ---- RF14 / T3: pagamento recusado ----

def test_pagamento_recusado_libera_a_reserva(api, config, sessao, tokens):
    pedido = criar_pedido(api, PEDIDO_APP, tokens["maria"])
    pagamento = pagar_online(api, pedido["id"], tokens["maria"]).json()
    assert estoque(sessao, 1, 1) == (50, 2)
    decidir(api, config, pagamento["transacao_gateway"], "RECUSADO", "Cartão sem limite")
    detalhe = consultar(api, pedido["id"], tokens["maria"])
    assert detalhe["status"] == "PAGAMENTO_RECUSADO"
    assert detalhe["pagamento"]["status"] == "RECUSADO" and detalhe["pagamento"]["motivo_recusa"] == "Cartão sem limite"
    assert estoque(sessao, 1, 1) == (50, 0)  # T3: reserva liberada


def test_pagamento_online_de_outro_dono_ou_fora_do_estado(api, tokens):
    pedido = criar_pedido(api, PEDIDO_APP, tokens["maria"])
    alheio = pagar_online(api, pedido["id"], tokens["joao"])
    assert alheio.status_code == 404 and codigo(alheio) == "NAO_ENCONTRADO"  # OWASP API1
    funcionario = pagar_online(api, pedido["id"], tokens["matriz"])
    assert funcionario.status_code == 404 and codigo(funcionario) == "NAO_ENCONTRADO"  # contrato sem 403
    sem_token = api.post(f"/api/v1/pedidos/{pedido['id']}/pagamentos", json={"forma": "PIX"})
    assert sem_token.status_code == 401 and codigo(sem_token) == "NAO_AUTENTICADO"

    dinheiro = pagar_online(api, pedido["id"], tokens["maria"], "DINHEIRO")
    assert dinheiro.status_code == 422 and codigo(dinheiro) == "VALIDACAO"  # D14: dinheiro só no balcão
    com_valor = api.post(
        f"/api/v1/pedidos/{pedido['id']}/pagamentos", json={"forma": "PIX", "valor": "0.01"}, headers=auth(tokens["maria"])
    )
    assert com_valor.status_code == 422 and codigo(com_valor) == "VALIDACAO"  # OWASP API3

    _cancelar(api, pedido["id"], tokens["maria"])
    cancelado = pagar_online(api, pedido["id"], tokens["maria"])
    assert cancelado.status_code == 409 and codigo(cancelado) == "PEDIDO_NAO_PAGAVEL"


def test_prazo_vencido_antes_da_expiracao_rodar_da_409(api):
    pedido = criar_pedido(api)
    api.app.state.relogio = lambda: DEPOIS_DO_PRAZO
    resposta = pagar_online(api, pedido["id"], pedido["token_pedido"])
    assert resposta.status_code == 409 and codigo(resposta) == "PEDIDO_NAO_PAGAVEL"  # RN10


def test_gateway_fora_do_ar_da_503_e_a_nova_tentativa_reaproveita_o_pendente(api, sessao):
    """ERR-003: o PENDENTE fica gravado sem transação, e a nova tentativa usa o mesmo pagamento."""
    pedido = criar_pedido(api)
    cliente = api.app.state.cliente_gateway
    api.app.state.cliente_gateway = ClienteGateway(None)  # sem gateway
    falha = pagar_online(api, pedido["id"], pedido["token_pedido"])
    assert falha.status_code == 503 and codigo(falha) == "GATEWAY_INDISPONIVEL"
    linha = sessao.execute(
        text("SELECT status, transacao_gateway FROM pagamento WHERE pedido_id = :id"), {"id": pedido["id"]}
    ).one()
    assert linha.status == "PENDENTE" and linha.transacao_gateway is None

    api.app.state.cliente_gateway = cliente
    nova = pagar_online(api, pedido["id"], pedido["token_pedido"])
    assert nova.status_code == 202 and nova.json()["transacao_gateway"].startswith("sim_")
    total = sessao.scalar(text("SELECT COUNT(*) FROM pagamento WHERE pedido_id = :id"), {"id": pedido["id"]})
    assert total == 1  # um pagamento por pedido (M05)


# ---- RF14 / T2: pagamento no balcão (D14) ----

def test_atendente_confirma_pagamento_no_balcao(api, sessao, tokens):
    pedido = criar_pedido(api, PEDIDO_BALCAO, tokens["atendente_recife"])
    resposta = _balcao(api, pedido["id"], tokens["atendente_recife"])
    assert resposta.status_code == 201
    pagamento = resposta.json()
    assert pagamento["tipo"] == "BALCAO" and pagamento["forma"] == "DINHEIRO"
    assert pagamento["status"] == "APROVADO" and pagamento["transacao_gateway"] is None and pagamento["valor"] == "37.80"
    detalhe = consultar(api, pedido["id"], tokens["atendente_recife"])
    assert detalhe["status"] == "PAGO" and detalhe["historico"][-1]["origem"] == "FUNCIONARIO"
    assert estoque(sessao, 1, 1) == (48, 0)
    de_novo = _balcao(api, pedido["id"], tokens["atendente_recife"])
    assert de_novo.status_code == 409 and codigo(de_novo) == "PEDIDO_NAO_PAGAVEL"


def test_balcao_com_perfil_unidade_ou_estado_errado(api, tokens):
    pedido = criar_pedido(api)
    for nome in ("cozinha_recife", "gerente_recife", "maria"):
        negado = _balcao(api, pedido["id"], tokens[nome])
        assert negado.status_code == 403 and codigo(negado) == "SEM_PERMISSAO", nome
    outra = _balcao(api, pedido["id"], tokens["atendente_fortaleza"])
    assert outra.status_code == 403 and codigo(outra) == "SEM_PERMISSAO"
    inexistente = _balcao(api, 999999, tokens["atendente_recife"])
    assert inexistente.status_code == 404 and codigo(inexistente) == "NAO_ENCONTRADO"

    pagar_online(api, pedido["id"], pedido["token_pedido"])  # já tem pagamento online pendente
    conflito = _balcao(api, pedido["id"], tokens["atendente_recife"], "PIX")
    assert conflito.status_code == 409 and codigo(conflito) == "PEDIDO_NAO_PAGAVEL"


# ---- RF12 + D69: cancelamento de pedido pago pede o estorno ----

def test_cancelar_pedido_pago_online_estorna_pelo_gateway(api, config, sessao, tokens):
    pedido = criar_pedido(api, PEDIDO_APP, tokens["maria"])
    pagamento = pagar_online(api, pedido["id"], tokens["maria"]).json()
    decidir(api, config, pagamento["transacao_gateway"], "APROVADO")
    resposta = _cancelar(api, pedido["id"], tokens["maria"])  # T9
    assert resposta.status_code == 200 and resposta.json()["status"] == "CANCELADO"
    # Estorno pedido depois do COMMIT (D33); o refund.completed já voltou pelo webhook
    assert consultar(api, pedido["id"], tokens["maria"])["pagamento"]["status"] == "ESTORNADO"
    assert estoque(sessao, 1, 1) == (50, 0)  # T9: a baixa voltou ao saldo (D25)


def test_cancelar_pedido_pago_no_balcao_estorna_no_caixa(api, tokens):
    pedido = criar_pedido(api, PEDIDO_BALCAO, tokens["atendente_recife"])
    _balcao(api, pedido["id"], tokens["atendente_recife"])
    resposta = _cancelar(api, pedido["id"], tokens["gerente_recife"])
    assert resposta.status_code == 200
    assert consultar(api, pedido["id"], tokens["gerente_recife"])["pagamento"]["status"] == "ESTORNADO"
