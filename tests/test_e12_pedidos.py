"""E12 — Pedidos multicanal e máquina de estados (RF09–RF12, RF15; RN05–RN08, RN10; T1, T5–T11).

Dados da carga de exemplo (D55): Recife (1, COMPLETA, 06:00–22:00), Fortaleza
(2, REDUZIDA, 07:00–21:00), Salvador (3, inativa). Estoque pequeno de
propósito: Baião de dois (2) em Recife tem 3 unidades. Em Fortaleza o Baião
não está no cardápio (RN02) e o suco (4) está indisponível.

O relógio da API fica fixo ao meio-dia de Recife (D70), para os testes não
dependerem da hora em que rodam. O pagamento só chega na E13: para testar
T6–T11, o helper ``_pagar`` faz no banco o que o T2 fará (status PAGO e baixa
do estoque), dentro da transação que é desfeita no fim do teste (D64, D69).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from tests.apoio import auth, codigo

MEIO_DIA_RECIFE = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)  # 12:00 em UTC−3
MADRUGADA_RECIFE = datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)  # 02:00 em UTC−3

PEDIDO_APP = {"unidade_id": 1, "canal": "APP", "itens": [{"produto_id": 1, "quantidade": 2}, {"produto_id": 5, "quantidade": 1}]}
JUSTIFICATIVA = "Cliente desistiu do pedido"


@pytest.fixture(autouse=True)
def relogio_fixo(api):
    api.app.state.relogio = lambda: MEIO_DIA_RECIFE


def _estoque(sessao, unidade_id: int, produto_id: int) -> tuple[int, int]:
    linha = sessao.execute(
        text("SELECT quantidade, quantidade_reservada FROM estoque WHERE unidade_id = :u AND produto_id = :p"),
        {"u": unidade_id, "p": produto_id},
    ).one()
    return linha.quantidade, linha.quantidade_reservada


def _pagar(sessao, pedido: dict) -> None:
    """Simula o T2 da E13: pedido PAGO e reserva convertida em baixa (D06)."""
    sessao.execute(text("UPDATE pedido SET status = 'PAGO', expira_em = NULL WHERE id = :id"), {"id": pedido["id"]})
    for item in pedido["itens"]:
        sessao.execute(
            text(
                "UPDATE estoque SET quantidade = quantidade - :q, quantidade_reservada = quantidade_reservada - :q "
                "WHERE unidade_id = :u AND produto_id = :p"
            ),
            {"q": item["quantidade"], "u": pedido["unidade_id"], "p": item["produto_id"]},
        )
    sessao.expire_all()


def _criar(api, corpo=PEDIDO_APP, token: str | None = None):
    return api.post("/api/v1/pedidos", json=corpo, headers=auth(token) if token else {})


def _avancar(api, pedido_id: int, status: str, token: str):
    return api.patch(f"/api/v1/pedidos/{pedido_id}/status", json={"status": status}, headers=auth(token))


def _cancelar(api, pedido_id: int, token: str, justificativa: str = JUSTIFICATIVA):
    return api.post(
        f"/api/v1/pedidos/{pedido_id}/cancelamento", json={"justificativa": justificativa}, headers=auth(token)
    )


# ---- RF09 / T1: criar pedido ----

def test_pedido_anonimo_reserva_estoque_e_devolve_token(api, sessao):
    resposta = _criar(api)
    assert resposta.status_code == 201
    pedido = resposta.json()
    assert resposta.headers["Location"] == f"/api/v1/pedidos/{pedido['id']}"
    assert pedido["status"] == "AGUARDANDO_PAGAMENTO" and pedido["cliente_id"] is None
    assert pedido["valor_total"] == "43.30"  # 2 × 18.90 + 5.50, preço do cardápio (M08)
    assert pedido["itens"][0] == {
        "produto_id": 1, "nome": "Tapioca de carne de sol", "quantidade": 2, "preco_unitario": "18.90", "subtotal": "37.80"
    }
    assert pedido["criado_em"] == "2026-11-23T15:00:00Z" and pedido["expira_em"] == "2026-11-23T15:15:00Z"  # RN10
    assert pedido["token_pedido"]  # D46
    assert _estoque(sessao, 1, 1) == (50, 2) and _estoque(sessao, 1, 5) == (80, 1)  # RN06


def test_cliente_cria_pedido_pickup_sem_token_pedido(api, tokens):
    resposta = _criar(api, {**PEDIDO_APP, "canal": "PICKUP"}, tokens["maria"])
    assert resposta.status_code == 201
    assert resposta.json()["cliente_id"] is not None and resposta.json()["token_pedido"] is None


def test_atendente_cria_pedido_no_balcao_da_propria_unidade(api, tokens):
    balcao = {**PEDIDO_APP, "canal": "BALCAO"}
    assert _criar(api, balcao, tokens["atendente_recife"]).status_code == 201
    outra = _criar(api, {**balcao, "unidade_id": 2, "itens": [{"produto_id": 1, "quantidade": 1}]}, tokens["atendente_recife"])
    assert outra.status_code == 403 and codigo(outra) == "SEM_PERMISSAO"  # RN12


def test_canal_e_perfil_sem_permissao(api, tokens):
    anonimo_balcao = _criar(api, {**PEDIDO_APP, "canal": "BALCAO"})
    assert anonimo_balcao.status_code == 401 and codigo(anonimo_balcao) == "NAO_AUTENTICADO"
    cliente_totem = _criar(api, {**PEDIDO_APP, "canal": "TOTEM"}, tokens["maria"])
    assert cliente_totem.status_code == 403 and codigo(cliente_totem) == "SEM_PERMISSAO"
    gerente = _criar(api, {**PEDIDO_APP, "canal": "BALCAO"}, tokens["gerente_recife"])
    assert gerente.status_code == 403 and codigo(gerente) == "SEM_PERMISSAO"


def test_unidade_inexistente_inativa_ou_fora_do_horario(api):
    inexistente = _criar(api, {**PEDIDO_APP, "unidade_id": 999})
    assert inexistente.status_code == 404 and codigo(inexistente) == "NAO_ENCONTRADO"
    inativa = _criar(api, {**PEDIDO_APP, "unidade_id": 3})
    assert inativa.status_code == 409 and codigo(inativa) == "UNIDADE_FECHADA"  # RN05
    api.app.state.relogio = lambda: MADRUGADA_RECIFE
    fechada = _criar(api)
    assert fechada.status_code == 409 and codigo(fechada) == "UNIDADE_FECHADA"


def test_item_fora_do_cardapio_ou_indisponivel(api):
    fortaleza = {"unidade_id": 2, "canal": "APP", "itens": [{"produto_id": 2, "quantidade": 1}, {"produto_id": 4, "quantidade": 1}]}
    resposta = _criar(api, fortaleza)
    assert resposta.status_code == 409 and codigo(resposta) == "ITEM_INDISPONIVEL"
    campos = [d["campo"] for d in resposta.json()["erro"]["detalhes"]]
    assert campos == ["itens[0].produto_id", "itens[1].produto_id"]  # Baião (RN02) e suco indisponível
    inativo = _criar(api, {**PEDIDO_APP, "itens": [{"produto_id": 7, "quantidade": 1}]})
    assert inativo.status_code == 409 and codigo(inativo) == "ITEM_INDISPONIVEL"


def test_estoque_insuficiente_nao_reserva_nenhum_item(api, sessao):
    corpo = {**PEDIDO_APP, "itens": [{"produto_id": 1, "quantidade": 1}, {"produto_id": 2, "quantidade": 4}]}
    resposta = _criar(api, corpo)
    assert resposta.status_code == 409 and codigo(resposta) == "ESTOQUE_INSUFICIENTE"
    assert resposta.json()["erro"]["detalhes"][0] == {
        "campo": "itens[1].produto_id", "valor": 2, "problema": "saldo disponível: 3"
    }
    assert _estoque(sessao, 1, 1) == (50, 0)  # a reserva do item 1 foi desfeita (D27)


def test_produto_repetido_ou_preco_no_corpo_da_422(api):
    repetido = _criar(api, {**PEDIDO_APP, "itens": [{"produto_id": 1, "quantidade": 1}, {"produto_id": 1, "quantidade": 2}]})
    assert repetido.status_code == 422 and codigo(repetido) == "VALIDACAO"
    assert repetido.json()["erro"]["detalhes"][0]["campo"] == "itens[1].produto_id"
    com_preco = _criar(api, {**PEDIDO_APP, "itens": [{"produto_id": 1, "quantidade": 1, "preco_unitario": "0.01"}]})
    assert com_preco.status_code == 422 and codigo(com_preco) == "VALIDACAO"  # OWASP API3


# ---- RF10: consultar e painel ----

def test_token_pedido_so_abre_o_proprio_pedido(api):
    primeiro, segundo = _criar(api).json(), _criar(api).json()
    resposta = api.get(f"/api/v1/pedidos/{primeiro['id']}", headers=auth(primeiro["token_pedido"]))
    assert resposta.status_code == 200
    detalhe = resposta.json()
    assert detalhe["historico"] == [{"status": "AGUARDANDO_PAGAMENTO", "origem": "CLIENTE", "em": "2026-11-23T15:00:00Z"}]
    assert detalhe["pagamento"] is None and detalhe["token_pedido"] is None  # pagamento: E13
    alheio = api.get(f"/api/v1/pedidos/{segundo['id']}", headers=auth(primeiro["token_pedido"]))
    assert alheio.status_code == 404 and codigo(alheio) == "NAO_ENCONTRADO"  # OWASP API1
    sem_token = api.get(f"/api/v1/pedidos/{primeiro['id']}")
    assert sem_token.status_code == 401 and codigo(sem_token) == "NAO_AUTENTICADO"


def test_pedido_de_outro_cliente_ou_outra_unidade_da_404(api, tokens):
    pedido = _criar(api, PEDIDO_APP, tokens["maria"]).json()
    assert api.get(f"/api/v1/pedidos/{pedido['id']}", headers=auth(tokens["maria"])).status_code == 200
    assert api.get(f"/api/v1/pedidos/{pedido['id']}", headers=auth(tokens["joao"])).status_code == 404
    assert api.get(f"/api/v1/pedidos/{pedido['id']}", headers=auth(tokens["gerente_fortaleza"])).status_code == 404
    assert api.get(f"/api/v1/pedidos/{pedido['id']}", headers=auth(tokens["matriz"])).status_code == 200


def test_painel_da_unidade_filtra_por_status(api, tokens):
    pedido = _criar(api).json()
    resposta = api.get(
        "/api/v1/unidades/1/pedidos", params={"status": "AGUARDANDO_PAGAMENTO"}, headers=auth(tokens["cozinha_recife"])
    )
    assert resposta.status_code == 200
    assert pedido["id"] in [p["id"] for p in resposta.json()["itens"]]
    assert all(p["status"] == "AGUARDANDO_PAGAMENTO" for p in resposta.json()["itens"])
    vazio = api.get("/api/v1/unidades/1/pedidos", params={"status": "ENTREGUE"}, headers=auth(tokens["matriz"]))
    assert vazio.json() == {"itens": [], "total": 0}


def test_painel_de_outra_unidade_ou_sem_perfil(api, tokens):
    outra = api.get("/api/v1/unidades/1/pedidos", headers=auth(tokens["atendente_fortaleza"]))
    assert outra.status_code == 403 and codigo(outra) == "SEM_PERMISSAO"
    cliente = api.get("/api/v1/unidades/1/pedidos", headers=auth(tokens["maria"]))
    assert cliente.status_code == 403 and codigo(cliente) == "SEM_PERMISSAO"
    inexistente = api.get("/api/v1/unidades/999/pedidos", headers=auth(tokens["matriz"]))
    assert inexistente.status_code == 404 and codigo(inexistente) == "NAO_ENCONTRADO"


# ---- RF11 / T6–T8: avançar status ----

def test_fluxo_completo_ate_entregue(api, sessao, tokens):
    pedido = _criar(api).json()
    _pagar(sessao, pedido)
    assert _avancar(api, pedido["id"], "EM_PREPARO", tokens["cozinha_recife"]).json()["status"] == "EM_PREPARO"
    assert _avancar(api, pedido["id"], "PRONTO", tokens["cozinha_recife"]).json()["status"] == "PRONTO"
    entregue = _avancar(api, pedido["id"], "ENTREGUE", tokens["atendente_recife"])
    assert entregue.status_code == 200 and entregue.json()["status"] == "ENTREGUE"
    historico = api.get(f"/api/v1/pedidos/{pedido['id']}", headers=auth(tokens["matriz"])).json()["historico"]
    assert [h["status"] for h in historico] == ["AGUARDANDO_PAGAMENTO", "EM_PREPARO", "PRONTO", "ENTREGUE"]
    # A linha do PAGO entra pelo PagamentoService na E13; aqui o helper só simula o status


def test_transicao_fora_da_tabela_da_409(api, tokens):
    pedido = _criar(api).json()
    resposta = _avancar(api, pedido["id"], "EM_PREPARO", tokens["cozinha_recife"])  # ainda não foi pago
    assert resposta.status_code == 409 and codigo(resposta) == "TRANSICAO_INVALIDA"  # RN07
    assert resposta.json()["erro"]["detalhes"][0]["problema"] == "status atual: AGUARDANDO_PAGAMENTO"


def test_avancar_com_perfil_ou_unidade_errada_da_403(api, sessao, tokens):
    pedido = _criar(api).json()
    _pagar(sessao, pedido)
    atendente = _avancar(api, pedido["id"], "EM_PREPARO", tokens["atendente_recife"])
    assert atendente.status_code == 403 and codigo(atendente) == "SEM_PERMISSAO"
    outra = _avancar(api, pedido["id"], "EM_PREPARO", tokens["cozinha_fortaleza"])
    assert outra.status_code == 403 and codigo(outra) == "SEM_PERMISSAO"
    inexistente = _avancar(api, 999999, "EM_PREPARO", tokens["cozinha_recife"])
    assert inexistente.status_code == 404 and codigo(inexistente) == "NAO_ENCONTRADO"


# ---- RF12 / T5, T9–T11: cancelar ----

def test_cancelamento_antes_do_pagamento_libera_reserva(api, sessao):
    pedido = _criar(api).json()
    resposta = _cancelar(api, pedido["id"], pedido["token_pedido"])
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "CANCELADO" and resposta.json()["expira_em"] is None
    assert _estoque(sessao, 1, 1) == (50, 0)  # T5: reserva liberada
    de_novo = _cancelar(api, pedido["id"], pedido["token_pedido"])
    assert de_novo.status_code == 409 and codigo(de_novo) == "TRANSICAO_INVALIDA"  # estado final


def test_justificativa_curta_ou_em_branco_da_422(api):
    pedido = _criar(api).json()
    curta = _cancelar(api, pedido["id"], pedido["token_pedido"], "desisti")
    assert curta.status_code == 422 and codigo(curta) == "VALIDACAO"
    em_branco = _cancelar(api, pedido["id"], pedido["token_pedido"], " " * 12)
    assert em_branco.status_code == 422 and codigo(em_branco) == "JUSTIFICATIVA_OBRIGATORIA"  # RN08


def test_cliente_cancela_pedido_pago_e_estoque_volta(api, sessao, tokens):
    pedido = _criar(api, PEDIDO_APP, tokens["maria"]).json()
    _pagar(sessao, pedido)
    assert _estoque(sessao, 1, 1) == (48, 0)  # baixa feita pelo helper
    resposta = _cancelar(api, pedido["id"], tokens["maria"])
    assert resposta.status_code == 200 and resposta.json()["status"] == "CANCELADO"
    assert _estoque(sessao, 1, 1) == (50, 0)  # T9: devolvido ao saldo (D25)


def test_gerente_cancela_em_preparo_e_estoque_nao_volta(api, sessao, tokens):
    pedido = _criar(api, PEDIDO_APP, tokens["maria"]).json()
    _pagar(sessao, pedido)
    _avancar(api, pedido["id"], "EM_PREPARO", tokens["cozinha_recife"])
    cliente = _cancelar(api, pedido["id"], tokens["maria"])
    assert cliente.status_code == 409 and codigo(cliente) == "TRANSICAO_INVALIDA"  # só o gerente faz T10
    resposta = _cancelar(api, pedido["id"], tokens["gerente_recife"])
    assert resposta.status_code == 200 and resposta.json()["status"] == "CANCELADO"
    assert _estoque(sessao, 1, 1) == (48, 0)  # T10: perda (D25)
    historico = api.get(f"/api/v1/pedidos/{pedido['id']}", headers=auth(tokens["maria"])).json()["historico"]
    assert historico[-1] == {"status": "CANCELADO", "origem": "FUNCIONARIO", "em": "2026-11-23T15:00:00Z"}


def test_cancelar_sem_perfil_ou_de_outra_unidade_da_403(api, tokens):
    pedido = _criar(api).json()
    atendente = _cancelar(api, pedido["id"], tokens["atendente_recife"])
    assert atendente.status_code == 403 and codigo(atendente) == "SEM_PERMISSAO"
    outra = _cancelar(api, pedido["id"], tokens["gerente_fortaleza"])
    assert outra.status_code == 403 and codigo(outra) == "SEM_PERMISSAO"
    alheio = _cancelar(api, pedido["id"], tokens["joao"])
    assert alheio.status_code == 404 and codigo(alheio) == "NAO_ENCONTRADO"
