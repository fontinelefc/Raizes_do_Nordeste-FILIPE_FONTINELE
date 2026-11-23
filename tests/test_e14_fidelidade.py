"""E14 — Dados do titular, extrato e consentimentos LGPD (RF17, RF20, RF25; RN16, RN17; UC21; D42, D75).

Carga de exemplo: a Maria (cliente 1, DE_25_A_34) tem consentimento FIDELIDADE
vigente (versão 1.0); o João (cliente 2, MENOR_18) não tem nenhum.
"""

import pytest

from tests.apoio import CONSENTIMENTO, auth, auditoria, codigo, criar_pedido

ROTAS_ME = [
    ("GET", "/api/v1/clientes/me", None),
    ("GET", "/api/v1/clientes/me/pontos", None),
    ("GET", "/api/v1/clientes/me/consentimentos", None),
    ("POST", "/api/v1/clientes/me/consentimentos", CONSENTIMENTO),
    ("DELETE", "/api/v1/clientes/me/consentimentos/FIDELIDADE", None),
]


def _conceder(api, token: str, **corpo):
    return api.post("/api/v1/clientes/me/consentimentos", json={**CONSENTIMENTO, **corpo}, headers=auth(token))


def _revogar(api, token: str):
    return api.delete("/api/v1/clientes/me/consentimentos/FIDELIDADE", headers=auth(token))


def _consentimentos(api, token: str) -> list[dict]:
    resposta = api.get("/api/v1/clientes/me/consentimentos", headers=auth(token))
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


# ---- Endpoint 20: dados do titular (RF17, RF25) ----

def test_cliente_consulta_os_proprios_dados_e_o_acesso_fica_auditado(api, sessao, tokens):
    resposta = api.get("/api/v1/clientes/me", headers=auth(tokens["maria"]))
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["id"] == 1 and dados["email"] == "maria@cliente.example" and dados["saldo_pontos"] == 0
    assert "senha_hash" not in dados and dados["criado_em"].endswith("Z")

    registros = auditoria(sessao, "LER_DADOS_CLIENTE")
    assert len(registros) == 1
    assert registros[0] | {"detalhes": None} == {
        "ator_tipo": "CLIENTE",
        "ator_id": 1,
        "acao": "LER_DADOS_CLIENTE",
        "entidade": "cliente",
        "entidade_id": 1,
        "unidade_id": None,
        "detalhes": None,
        "ip_origem": "testclient",
    }


@pytest.mark.parametrize("metodo, rota, corpo", ROTAS_ME)
def test_rotas_me_exigem_token_de_cliente(api, tokens, metodo, rota, corpo):
    """D42, D75: sem token, com token de funcionário ou com token_pedido, 401."""
    pedido = criar_pedido(api)  # anônimo, devolve token_pedido (D46)
    for token in (None, tokens["gerente_recife"], pedido["token_pedido"]):
        headers = auth(token) if token else {}
        resposta = api.request(metodo, rota, json=corpo, headers=headers)
        assert resposta.status_code == 401 and codigo(resposta) == "NAO_AUTENTICADO", (rota, token)


# ---- Endpoint 21: extrato (RF17) ----

def test_extrato_sem_movimentacao_vem_vazio(api, tokens):
    resposta = api.get("/api/v1/clientes/me/pontos", headers=auth(tokens["joao"]))
    assert resposta.status_code == 200 and resposta.json() == {"itens": [], "total": 0}
    acima = api.get("/api/v1/clientes/me/pontos?limit=101", headers=auth(tokens["joao"]))
    assert acima.status_code == 422 and codigo(acima) == "VALIDACAO"


# ---- Endpoints 22–24: consentimentos (RF20, UC21) ----

def test_lista_so_os_consentimentos_do_proprio_cliente(api, sessao, tokens):
    maria = _consentimentos(api, tokens["maria"])
    assert len(maria) == 1
    assert maria[0]["finalidade"] == "FIDELIDADE" and maria[0]["versao_termo"] == "1.0"
    assert maria[0]["revogado_em"] is None and maria[0]["concedido_em"].endswith("Z")
    assert _consentimentos(api, tokens["joao"]) == []
    assert [r["ator_id"] for r in auditoria(sessao, "LER_CONSENTIMENTOS")] == [1, 2]


def test_segundo_consentimento_vigente_da_409(api, tokens):
    resposta = _conceder(api, tokens["maria"])
    assert resposta.status_code == 409 and codigo(resposta) == "CONSENTIMENTO_VIGENTE"


def test_menor_de_18_precisa_da_autorizacao_do_responsavel(api, sessao, tokens):
    """RN17, UC21-E1."""
    sem = _conceder(api, tokens["joao"])
    assert sem.status_code == 422 and codigo(sem) == "AUTORIZACAO_RESPONSAVEL_OBRIGATORIA"
    assert _consentimentos(api, tokens["joao"]) == []

    com = _conceder(api, tokens["joao"], autorizado_responsavel=True)
    assert com.status_code == 201
    corpo = com.json()
    assert corpo["autorizado_responsavel"] is True and corpo["revogado_em"] is None
    registro = auditoria(sessao, "CONCEDER_CONSENTIMENTO")[0]
    assert registro["ator_id"] == 2 and registro["entidade_id"] == corpo["id"]
    assert registro["detalhes"] == {"finalidade": "FIDELIDADE", "versao_termo": "1.0"}  # sem dados pessoais


def test_revogar_preserva_o_historico_e_permite_novo_aceite(api, sessao, tokens):
    """RN16, M09: a revogação preenche revogado_em; o novo aceite é uma nova linha."""
    revogado = _revogar(api, tokens["maria"])
    assert revogado.status_code == 204 and revogado.content == b""
    de_novo = _revogar(api, tokens["maria"])
    assert de_novo.status_code == 404 and codigo(de_novo) == "NAO_ENCONTRADO"

    novo = _conceder(api, tokens["maria"], versao_termo="2.0")
    assert novo.status_code == 201
    historico = _consentimentos(api, tokens["maria"])
    assert [c["versao_termo"] for c in historico] == ["1.0", "2.0"]
    assert historico[0]["revogado_em"] is not None and historico[1]["revogado_em"] is None
    assert len(auditoria(sessao, "REVOGAR_CONSENTIMENTO")) == 1  # o 404 não grava nada


def test_corpo_do_consentimento_recusa_campo_extra_e_finalidade_invalida(api, tokens):
    extra = _conceder(api, tokens["joao"], autorizado_responsavel=True, cliente_id=1)  # OWASP API3
    assert extra.status_code == 422 and codigo(extra) == "VALIDACAO"
    finalidade = _conceder(api, tokens["joao"], finalidade="CAMPANHAS")
    assert finalidade.status_code == 422 and codigo(finalidade) == "VALIDACAO"
    rota = api.delete("/api/v1/clientes/me/consentimentos/CAMPANHAS", headers=auth(tokens["maria"]))
    assert rota.status_code == 422 and codigo(rota) == "VALIDACAO"
