"""E12 — Consulta do estoque da unidade (RF15; RN12).

Carga de exemplo (D45): Recife tem 6 linhas de estoque; Fortaleza, 5.
"""

from tests.apoio import auth, codigo
from tests.test_e12_pedidos import MEIO_DIA_RECIFE


def test_gerente_consulta_estoque_da_propria_unidade(api, tokens):
    resposta = api.get("/api/v1/unidades/1/estoque", headers=auth(tokens["gerente_recife"]))
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == 6 and [e["produto_id"] for e in corpo["itens"]] == [1, 2, 3, 4, 5, 6]
    baiao = corpo["itens"][1]
    assert (baiao["quantidade"], baiao["quantidade_reservada"], baiao["disponivel"]) == (3, 0, 3)
    assert baiao["atualizado_em"].endswith("Z")


def test_disponivel_desconta_a_reserva_do_pedido(api, tokens):
    api.app.state.relogio = lambda: MEIO_DIA_RECIFE  # D70: unidade aberta
    pedido = {"unidade_id": 1, "canal": "APP", "itens": [{"produto_id": 2, "quantidade": 2}]}
    assert api.post("/api/v1/pedidos", json=pedido).status_code == 201
    baiao = api.get("/api/v1/unidades/1/estoque", headers=auth(tokens["matriz"])).json()["itens"][1]
    assert (baiao["quantidade"], baiao["quantidade_reservada"], baiao["disponivel"]) == (3, 2, 1)


def test_matriz_pagina_o_estoque(api, tokens):
    resposta = api.get("/api/v1/unidades/2/estoque", params={"limit": 2, "offset": 1}, headers=auth(tokens["matriz"]))
    assert resposta.status_code == 200
    assert [e["produto_id"] for e in resposta.json()["itens"]] == [3, 4] and resposta.json()["total"] == 5


def test_estoque_de_outra_unidade_ou_sem_perfil_da_403(api, tokens):
    outra = api.get("/api/v1/unidades/2/estoque", headers=auth(tokens["gerente_recife"]))
    assert outra.status_code == 403 and codigo(outra) == "SEM_PERMISSAO"  # RN12
    atendente = api.get("/api/v1/unidades/1/estoque", headers=auth(tokens["atendente_recife"]))
    assert atendente.status_code == 403 and codigo(atendente) == "SEM_PERMISSAO"


def test_estoque_sem_token_ou_unidade_inexistente(api, tokens):
    sem_token = api.get("/api/v1/unidades/1/estoque")
    assert sem_token.status_code == 401 and codigo(sem_token) == "NAO_AUTENTICADO"
    inexistente = api.get("/api/v1/unidades/999/estoque", headers=auth(tokens["matriz"]))
    assert inexistente.status_code == 404 and codigo(inexistente) == "NAO_ENCONTRADO"
