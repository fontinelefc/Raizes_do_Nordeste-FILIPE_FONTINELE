"""E14 — Trilha de auditoria das operações sensíveis (RF25; RN13; ADR-07; D14, D24, D29, D57, D65).

Cada registro entra na mesma transação da operação: se a operação falha, nada
é gravado. O usuário ``raizes_app`` só tem SELECT e INSERT na tabela (D57).
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services.pedidos import PedidoService
from tests.apoio import (
    DEPOIS_DO_PRAZO,
    MEIO_DIA_RECIFE,
    PEDIDO_BALCAO,
    auditoria,
    auth,
    codigo,
    criar_pedido,
    decidir,
    pagar_online,
    pedido_pago_online,
)

JUSTIFICATIVA = "Cliente desistiu do pedido"
NOVA_UNIDADE = {
    "nome": "Raízes Natal — Ponta Negra",
    "tipo_operacao": "REDUZIDA",
    "cidade": "Natal",
    "uf": "RN",
    "horario_abertura": "10:00",
    "horario_fechamento": "22:00",
}


@pytest.fixture(autouse=True)
def relogio_fixo(api):
    api.app.state.relogio = lambda: MEIO_DIA_RECIFE


def _cancelar(api, pedido_id: int, token: str):
    return api.post(
        f"/api/v1/pedidos/{pedido_id}/cancelamento", json={"justificativa": JUSTIFICATIVA}, headers=auth(token)
    )


# ---- Pedidos e pagamentos (RN13, D14, D24) ----

def test_cancelamento_grava_quem_cancelou_e_o_antes_e_depois(api, config, sessao, tokens):
    pedido = pedido_pago_online(api, config, tokens["maria"])
    assert _cancelar(api, pedido["id"], tokens["maria"]).status_code == 200
    anonimo = criar_pedido(api)
    assert _cancelar(api, anonimo["id"], anonimo["token_pedido"]).status_code == 200

    pago, sem_login = auditoria(sessao, "CANCELAR_PEDIDO")
    assert (pago["ator_tipo"], pago["ator_id"], pago["entidade"], pago["entidade_id"], pago["unidade_id"]) == (
        "CLIENTE", 1, "pedido", pedido["id"], 1
    )
    assert pago["detalhes"] == {
        "antes": {"status": "PAGO"},
        "depois": {"status": "CANCELADO"},
        "justificativa": JUSTIFICATIVA,
        "pontos_estornados": 43,
    }
    assert (sem_login["ator_tipo"], sem_login["ator_id"]) == ("CLIENTE", None)  # token_pedido (D46)
    assert sem_login["detalhes"]["antes"] == {"status": "AGUARDANDO_PAGAMENTO"}


def test_cancelamento_recusado_nao_grava_auditoria(api, sessao, tokens):
    pedido = criar_pedido(api, token=tokens["maria"])
    negado = _cancelar(api, pedido["id"], tokens["cozinha_recife"])
    assert negado.status_code == 403 and codigo(negado) == "SEM_PERMISSAO"
    assert auditoria(sessao, "CANCELAR_PEDIDO") == []


def test_pagamento_no_balcao_fica_na_trilha(api, sessao, tokens):
    """D14: o pagamento fora do gateway é confirmado pelo atendente e auditado."""
    pedido = criar_pedido(api, PEDIDO_BALCAO, tokens["atendente_recife"])
    resposta = api.post(
        f"/api/v1/pedidos/{pedido['id']}/pagamentos/balcao", json={"forma": "DINHEIRO"}, headers=auth(tokens["atendente_recife"])
    )
    assert resposta.status_code == 201
    (registro,) = auditoria(sessao, "CONFIRMAR_PAGAMENTO_BALCAO")
    assert (registro["ator_tipo"], registro["ator_id"], registro["unidade_id"]) == ("FUNCIONARIO", 3, 1)
    assert registro["entidade"] == "pagamento" and registro["entidade_id"] == resposta.json()["pagamento_id"]
    assert registro["detalhes"] == {"pedido_id": pedido["id"], "forma": "DINHEIRO", "valor": "37.80"}


def test_aprovacao_tardia_grava_estorno_automatico(api, config, sessao):
    """D24: o pedido expirou antes da aprovação; o estorno automático fica registrado com o ator GATEWAY."""
    pedido = criar_pedido(api)
    transacao = pagar_online(api, pedido["id"], pedido["token_pedido"]).json()["transacao_gateway"]
    api.app.state.relogio = lambda: DEPOIS_DO_PRAZO
    assert PedidoService(sessao, config.jwt_segredo, lambda: DEPOIS_DO_PRAZO).expirar_vencidos() == 1
    decidir(api, config, transacao, "APROVADO")

    (registro,) = auditoria(sessao, "ESTORNO_AUTOMATICO")
    assert (registro["ator_tipo"], registro["ator_id"], registro["unidade_id"]) == ("GATEWAY", None, 1)
    assert registro["detalhes"] == {"pedido_id": pedido["id"], "status_pedido": "EXPIRADO", "valor": "43.30"}


# ---- Unidades e catálogo (D65) ----

def test_cadastro_e_alteracao_de_unidade_sao_auditados(api, sessao, tokens):
    criada = api.post("/api/v1/unidades", json=NOVA_UNIDADE, headers=auth(tokens["matriz"]))
    assert criada.status_code == 201
    unidade_id = criada.json()["id"]
    alterada = api.patch(f"/api/v1/unidades/{unidade_id}", json={"ativa": False}, headers=auth(tokens["matriz"]))
    assert alterada.status_code == 200

    (cadastro,) = auditoria(sessao, "CADASTRAR_UNIDADE")
    assert (cadastro["ator_tipo"], cadastro["ator_id"], cadastro["entidade_id"]) == ("FUNCIONARIO", 1, unidade_id)
    assert cadastro["detalhes"]["depois"]["cidade"] == "Natal"
    (alteracao,) = auditoria(sessao, "ALTERAR_UNIDADE")
    assert alteracao["detalhes"] == {"antes": {"ativa": True}, "depois": {"ativa": False}}


def test_alteracao_de_produto_guarda_o_antes_e_o_depois(api, sessao, tokens):
    resposta = api.patch("/api/v1/produtos/1", json={"preco_base": "19.50"}, headers=auth(tokens["matriz"]))
    assert resposta.status_code == 200
    (registro,) = auditoria(sessao, "ALTERAR_PRODUTO")
    assert registro["entidade"] == "produto" and registro["entidade_id"] == 1 and registro["unidade_id"] is None
    assert registro["detalhes"]["depois"] == {"preco_base": "19.50"}
    assert set(registro["detalhes"]["antes"]) == {"preco_base"}


def test_cardapio_auditado_so_quando_a_mudanca_e_aceita(api, sessao, tokens):
    """ADR-07: o 422 de preço fora da faixa desfaz tudo, inclusive o registro."""
    fora = api.put(
        "/api/v1/unidades/1/cardapio/1", json={"preco": "999.00", "disponivel": True}, headers=auth(tokens["gerente_recife"])
    )
    assert fora.status_code == 422 and codigo(fora) == "PRECO_FORA_DA_FAIXA"
    assert auditoria(sessao, "DEFINIR_ITEM_CARDAPIO") == []

    certo = api.put(
        "/api/v1/unidades/1/cardapio/1", json={"preco": "18.50", "disponivel": False}, headers=auth(tokens["gerente_recife"])
    )
    assert certo.status_code == 200
    (registro,) = auditoria(sessao, "DEFINIR_ITEM_CARDAPIO")
    assert (registro["ator_id"], registro["entidade_id"], registro["unidade_id"]) == (2, 1, 1)
    assert registro["detalhes"] == {
        "antes": {"preco": "18.90", "disponivel": True},
        "depois": {"preco": "18.50", "disponivel": False},
    }


# ---- A trilha não pode ser alterada pela aplicação (RN13, D57) ----

def test_raizes_app_nao_altera_nem_apaga_a_auditoria(api, sessao, tokens):
    api.get("/api/v1/clientes/me", headers=auth(tokens["maria"]))
    for comando in ("UPDATE registro_auditoria SET acao = 'X'", "DELETE FROM registro_auditoria"):
        with pytest.raises(DBAPIError) as erro:
            sessao.execute(text(comando))
        assert erro.value.orig.args[0] == 1142, comando  # 1142: comando negado ao usuário
