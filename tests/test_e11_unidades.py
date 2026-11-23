"""E11 — Unidades, catálogo e cardápio por unidade (RF03, RF04, RF05, RF08; RN01, RN02, RN12).

Dados da carga de exemplo (D55): Recife (1, COMPLETA), Fortaleza (2, REDUZIDA),
Salvador (3, inativa); 7 produtos, o 2 (Baião de dois) exige cozinha completa e
o 7 (Canjica) está inativo; o suco (4) está indisponível em Fortaleza.
"""

from tests.apoio import auth, codigo

NOVA_UNIDADE = {
    "nome": "Raízes Natal — Ponta Negra",
    "tipo_operacao": "REDUZIDA",
    "cidade": "Natal",
    "uf": "RN",
    "horario_abertura": "07:00",
    "horario_fechamento": "21:00",
}

NOVO_PRODUTO = {
    "codigo": "ACA-001",
    "nome": "Arrumadinho",
    "descricao": "Feijão-verde, charque e vinagrete",
    "categoria": "pratos",
    "preco_base": "24.90",
    "preco_minimo": "20.00",
    "preco_maximo": "30.00",
    "exige_cozinha_completa": False,
}


def _ids(resposta) -> list[int]:
    return [item.get("id", item.get("produto_id")) for item in resposta.json()["itens"]]


# ---- RF03: unidades ----

def test_lista_publica_so_traz_unidades_ativas(api):
    resposta = api.get("/api/v1/unidades")
    assert resposta.status_code == 200
    assert _ids(resposta) == [1, 2] and resposta.json()["total"] == 2  # Salvador está inativa
    recife = resposta.json()["itens"][0]
    assert recife["horario_abertura"] == "06:00" and recife["criado_em"].endswith("Z")


def test_lista_de_unidades_pagina_e_limita(api):
    pagina = api.get("/api/v1/unidades", params={"limit": 1, "offset": 1})
    assert _ids(pagina) == [2] and pagina.json()["total"] == 2
    acima = api.get("/api/v1/unidades", params={"limit": 500})
    assert acima.status_code == 422 and codigo(acima) == "VALIDACAO"  # OWASP API4


def test_matriz_cadastra_unidade(api, tokens):
    resposta = api.post("/api/v1/unidades", json=NOVA_UNIDADE, headers=auth(tokens["matriz"]))
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["ativa"] is True and corpo["horario_fechamento"] == "21:00"
    assert corpo["id"] in _ids(api.get("/api/v1/unidades"))


def test_cadastro_de_unidade_com_horario_invalido_da_422(api, tokens):
    resposta = api.post(
        "/api/v1/unidades", json={**NOVA_UNIDADE, "horario_abertura": "25:00"}, headers=auth(tokens["matriz"])
    )
    assert resposta.status_code == 422 and codigo(resposta) == "VALIDACAO"
    assert resposta.json()["erro"]["detalhes"][0]["campo"] == "horario_abertura"


def test_gerente_nao_cadastra_unidade(api, tokens):
    resposta = api.post("/api/v1/unidades", json=NOVA_UNIDADE, headers=auth(tokens["gerente_recife"]))
    assert resposta.status_code == 403 and codigo(resposta) == "SEM_PERMISSAO"


def test_matriz_reativa_unidade(api, tokens):
    resposta = api.patch("/api/v1/unidades/3", json={"ativa": True}, headers=auth(tokens["matriz"]))
    assert resposta.status_code == 200 and resposta.json()["ativa"] is True
    assert 3 in _ids(api.get("/api/v1/unidades"))


def test_alterar_unidade_inexistente_ou_com_null_e_recusado(api, tokens):
    inexistente = api.patch("/api/v1/unidades/999", json={"nome": "X"}, headers=auth(tokens["matriz"]))
    assert inexistente.status_code == 404 and codigo(inexistente) == "NAO_ENCONTRADO"
    nulo = api.patch("/api/v1/unidades/1", json={"nome": None}, headers=auth(tokens["matriz"]))
    assert nulo.status_code == 422 and codigo(nulo) == "VALIDACAO"


# ---- RF04: catálogo padrão da matriz ----

def test_matriz_e_gerente_veem_o_catalogo_completo(api, tokens):
    for conta in ("matriz", "gerente_recife"):
        resposta = api.get("/api/v1/produtos", headers=auth(tokens[conta]))
        assert resposta.status_code == 200 and resposta.json()["total"] == 7  # inclui o inativo
    canjica = resposta.json()["itens"][6]
    assert canjica["ativo"] is False and canjica["preco_base"] == "10.90"  # dinheiro como texto


def test_atendente_nao_ve_o_catalogo_de_gestao(api, tokens):
    resposta = api.get("/api/v1/produtos", headers=auth(tokens["atendente_recife"]))
    assert resposta.status_code == 403 and codigo(resposta) == "SEM_PERMISSAO"


def test_matriz_cadastra_produto(api, tokens):
    resposta = api.post("/api/v1/produtos", json=NOVO_PRODUTO, headers=auth(tokens["matriz"]))
    assert resposta.status_code == 201
    assert resposta.json()["ativo"] is True and resposta.json()["preco_base"] == "24.90"


def test_produto_com_codigo_repetido_da_409(api, tokens):
    resposta = api.post(
        "/api/v1/produtos", json={**NOVO_PRODUTO, "codigo": "TAP-001"}, headers=auth(tokens["matriz"])
    )
    assert resposta.status_code == 409 and codigo(resposta) == "CODIGO_JA_CADASTRADO"


def test_produto_com_faixa_de_preco_incoerente_da_422(api, tokens):
    # RN01: preco_minimo <= preco_base <= preco_maximo
    faixa = api.post(
        "/api/v1/produtos", json={**NOVO_PRODUTO, "preco_minimo": "26.00"}, headers=auth(tokens["matriz"])
    )
    assert faixa.status_code == 422 and codigo(faixa) == "VALIDACAO"
    formato = api.post("/api/v1/produtos", json={**NOVO_PRODUTO, "preco_base": "24.9"}, headers=auth(tokens["matriz"]))
    assert formato.status_code == 422 and codigo(formato) == "VALIDACAO"  # dinheiro com 2 casas


def test_matriz_altera_produto_e_a_faixa_continua_valida(api, tokens):
    ok = api.patch("/api/v1/produtos/1", json={"nome": "Tapioca de carne de sol (G)"}, headers=auth(tokens["matriz"]))
    assert ok.status_code == 200 and ok.json()["nome"] == "Tapioca de carne de sol (G)"
    # preco_minimo acima do preco_base atual (18.90) quebra a RN01
    faixa = api.patch("/api/v1/produtos/1", json={"preco_minimo": "19.00"}, headers=auth(tokens["matriz"]))
    assert faixa.status_code == 422 and codigo(faixa) == "VALIDACAO"
    inexistente = api.patch("/api/v1/produtos/999", json={"nome": "X"}, headers=auth(tokens["matriz"]))
    assert inexistente.status_code == 404 and codigo(inexistente) == "NAO_ENCONTRADO"


# ---- RF08: cardápio vigente da unidade (público) ----

def test_cardapio_de_recife_traz_os_6_produtos_ativos(api):
    resposta = api.get("/api/v1/unidades/1/cardapio")
    assert resposta.status_code == 200
    assert sorted(_ids(resposta)) == [1, 2, 3, 4, 5, 6] and resposta.json()["total"] == 6


def test_cardapio_de_fortaleza_esconde_item_indisponivel(api):
    resposta = api.get("/api/v1/unidades/2/cardapio")
    assert sorted(_ids(resposta)) == [1, 3, 5, 6]  # suco indisponível; Baião fora do cardápio
    tapioca = next(i for i in resposta.json()["itens"] if i["produto_id"] == 1)
    assert tapioca["preco"] == "19.90"  # preço local, não o preço base


def test_cardapio_de_unidade_inativa_ou_inexistente_da_404(api):
    for unidade in (3, 999):
        resposta = api.get(f"/api/v1/unidades/{unidade}/cardapio")
        assert resposta.status_code == 404 and codigo(resposta) == "NAO_ENCONTRADO"


def test_cardapio_de_unidade_reduzida_esconde_produto_que_exige_cozinha_completa(api, tokens):
    # RN02 também na leitura: se a matriz passar a exigir cozinha completa, Fortaleza deixa de oferecer
    api.patch("/api/v1/produtos/1", json={"exige_cozinha_completa": True}, headers=auth(tokens["matriz"]))
    assert 1 not in _ids(api.get("/api/v1/unidades/2/cardapio"))
    assert 1 in _ids(api.get("/api/v1/unidades/1/cardapio"))


# ---- RF05: preço e disponibilidade na unidade ----

def test_gerente_define_preco_local_dentro_da_faixa(api, tokens):
    resposta = api.put(
        "/api/v1/unidades/1/cardapio/1", json={"preco": "20.00", "disponivel": True}, headers=auth(tokens["gerente_recife"])
    )
    assert resposta.status_code == 200 and resposta.json()["preco"] == "20.00"
    tapioca = next(i for i in api.get("/api/v1/unidades/1/cardapio").json()["itens"] if i["produto_id"] == 1)
    assert tapioca["preco"] == "20.00"


def test_gerente_tira_item_do_cardapio(api, tokens):
    resposta = api.put(
        "/api/v1/unidades/1/cardapio/6", json={"preco": "8.90", "disponivel": False}, headers=auth(tokens["gerente_recife"])
    )
    assert resposta.status_code == 200 and resposta.json()["disponivel"] is False
    assert 6 not in _ids(api.get("/api/v1/unidades/1/cardapio"))


def test_gerente_nao_altera_cardapio_de_outra_unidade(api, tokens):
    # Nível 2 da autorização (RN12): unidade do token diferente da do recurso
    resposta = api.put(
        "/api/v1/unidades/2/cardapio/1", json={"preco": "20.00", "disponivel": True}, headers=auth(tokens["gerente_recife"])
    )
    assert resposta.status_code == 403 and codigo(resposta) == "SEM_PERMISSAO"


def test_preco_local_fora_da_faixa_da_422(api, tokens):
    # Tapioca: faixa 15.00 a 24.00 (RN01)
    resposta = api.put(
        "/api/v1/unidades/1/cardapio/1", json={"preco": "30.00", "disponivel": True}, headers=auth(tokens["gerente_recife"])
    )
    assert resposta.status_code == 422 and codigo(resposta) == "PRECO_FORA_DA_FAIXA"


def test_produto_que_exige_cozinha_completa_nao_entra_em_unidade_reduzida(api, tokens):
    # Baião de dois (2) em Fortaleza (REDUZIDA), RN02
    resposta = api.put(
        "/api/v1/unidades/2/cardapio/2", json={"preco": "32.90", "disponivel": True}, headers=auth(tokens["gerente_fortaleza"])
    )
    assert resposta.status_code == 409 and codigo(resposta) == "PRODUTO_INCOMPATIVEL_UNIDADE"


def test_matriz_inclui_produto_novo_no_cardapio_de_qualquer_unidade(api, tokens):
    produto = api.post("/api/v1/produtos", json=NOVO_PRODUTO, headers=auth(tokens["matriz"])).json()
    resposta = api.put(
        f"/api/v1/unidades/2/cardapio/{produto['id']}",
        json={"preco": "25.00", "disponivel": True},
        headers=auth(tokens["matriz"]),
    )
    assert resposta.status_code == 200
    assert produto["id"] in _ids(api.get("/api/v1/unidades/2/cardapio"))


def test_cardapio_com_produto_inexistente_da_404(api, tokens):
    resposta = api.put(
        "/api/v1/unidades/1/cardapio/999", json={"preco": "10.00", "disponivel": True}, headers=auth(tokens["matriz"])
    )
    assert resposta.status_code == 404 and codigo(resposta) == "NAO_ENCONTRADO"


def test_textos_com_acento_saem_em_utf8(api):
    # Pega carga feita com o cliente mysql em latin1, que grava "Café" como "CafÃ©" (ERR-006)
    nomes = [i["nome"] for i in api.get("/api/v1/unidades/2/cardapio").json()["itens"]]
    assert "Café coado" in nomes
    assert api.get("/api/v1/unidades").json()["itens"][0]["nome"] == "Raízes Recife — Boa Viagem"
