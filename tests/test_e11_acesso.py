"""E11 — Acesso: login, cadastro de cliente e autorização por função (RF01, RF02, UC16)."""

from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import text

from app.models.enums import Perfil
from app.nucleo.seguranca import Credencial, gerar_token
from tests.apoio import SENHA_EXEMPLO, auth, codigo

LOGIN = "/api/v1/auth/login"


def _login(api, email, senha=SENHA_EXEMPLO, tipo="FUNCIONARIO"):
    return api.post(LOGIN, json={"email": email, "senha": senha, "tipo": tipo})


# ---- RF01: login ----

def test_login_funcionario_devolve_jwt_com_perfil_e_unidade(api, config):
    resposta = _login(api, "gerente.recife@raizes.example")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["token_type"] == "bearer"
    assert corpo["perfil"] == "GERENTE" and corpo["unidade_id"] == 1
    assert corpo["expira_em"].endswith("Z")  # UTC (3.6.1)

    carga = jwt.decode(corpo["access_token"], config.jwt_segredo, algorithms=["HS256"])
    assert carga["sub"] == "2" and carga["tipo"] == "FUNCIONARIO"
    assert carga["perfil"] == "GERENTE" and carga["unidade_id"] == 1
    assert carga["exp"] - carga["iat"] == 3600  # 60 min (D42)


def test_login_cliente_devolve_jwt_sem_perfil(api, config):
    resposta = _login(api, "maria@cliente.example", tipo="CLIENTE")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["perfil"] is None and corpo["unidade_id"] is None
    carga = jwt.decode(corpo["access_token"], config.jwt_segredo, algorithms=["HS256"])
    assert carga["tipo"] == "CLIENTE" and "perfil" not in carga


def test_login_senha_errada_e_email_inexistente_dao_a_mesma_resposta(api):
    senha_errada = _login(api, "matriz@raizes.example", senha="SenhaErrada@1")
    sem_conta = _login(api, "ninguem@raizes.example")
    assert senha_errada.status_code == sem_conta.status_code == 401
    assert codigo(senha_errada) == codigo(sem_conta) == "CREDENCIAIS_INVALIDAS"
    assert senha_errada.json()["erro"]["mensagem"] == sem_conta.json()["erro"]["mensagem"]


def test_login_com_tipo_trocado_nao_acha_a_conta(api):
    # O campo tipo diz em qual tabela procurar (3.6.3)
    resposta = _login(api, "matriz@raizes.example", tipo="CLIENTE")
    assert resposta.status_code == 401 and codigo(resposta) == "CREDENCIAIS_INVALIDAS"


def test_login_de_funcionario_inativo_e_recusado(api, sessao):
    sessao.execute(text("UPDATE usuario SET ativo = FALSE WHERE id = 3"))
    resposta = _login(api, "atendente.recife@raizes.example")
    assert resposta.status_code == 401 and codigo(resposta) == "CREDENCIAIS_INVALIDAS"


def test_login_sem_tipo_e_recusado_na_validacao(api):
    resposta = api.post(LOGIN, json={"email": "matriz@raizes.example", "senha": SENHA_EXEMPLO})
    assert resposta.status_code == 422 and codigo(resposta) == "VALIDACAO"


# ---- RF01: cadastro de cliente ----

def test_cadastro_de_cliente_e_login_em_seguida(api):
    novo = {
        "nome": "Joana Teste",
        "email": "joana@cliente.example",
        "senha": "Joana@2026",
        "faixa_etaria": "DE_18_A_24",
    }
    resposta = api.post("/api/v1/clientes", json=novo)
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["email"] == novo["email"] and corpo["saldo_pontos"] == 0
    assert corpo["criado_em"].endswith("Z")
    assert "senha" not in corpo and "senha_hash" not in corpo

    login = _login(api, novo["email"], senha=novo["senha"], tipo="CLIENTE")
    assert login.status_code == 200


def test_cadastro_com_email_repetido_da_409(api):
    resposta = api.post(
        "/api/v1/clientes", json={"nome": "Outra Maria", "email": "maria@cliente.example", "senha": "Maria@2026"}
    )
    assert resposta.status_code == 409 and codigo(resposta) == "EMAIL_JA_CADASTRADO"


def test_cadastro_recusa_campo_extra(api):
    # OWASP API3: saldo_pontos não pode vir do corpo
    resposta = api.post(
        "/api/v1/clientes",
        json={"nome": "Pedro", "email": "pedro@cliente.example", "senha": "Pedro@2026", "saldo_pontos": 999},
    )
    assert resposta.status_code == 422 and codigo(resposta) == "VALIDACAO"


# ---- RF02: autenticação e autorização por função ----

def test_rota_protegida_sem_token_da_401(api):
    resposta = api.get("/api/v1/produtos")
    assert resposta.status_code == 401 and codigo(resposta) == "NAO_AUTENTICADO"


def test_token_adulterado_ou_de_outro_segredo_da_401(api, tokens):
    cabeca, carga, assinatura = tokens["matriz"].split(".")
    adulterado = ".".join([cabeca, carga, ("A" if assinatura[0] != "A" else "B") + assinatura[1:]])
    outro_segredo, _ = gerar_token(Credencial("FUNCIONARIO", 1, Perfil.MATRIZ, None), "outro-segredo-" + "1" * 40)
    for token in (adulterado, outro_segredo, "nao-e-um-jwt"):
        resposta = api.get("/api/v1/produtos", headers=auth(token))
        assert resposta.status_code == 401 and codigo(resposta) == "NAO_AUTENTICADO"


def test_token_expirado_da_401(api, config):
    token, expira_em = gerar_token(
        Credencial("FUNCIONARIO", 1, Perfil.MATRIZ, None), config.jwt_segredo, validade=timedelta(minutes=-1)
    )
    assert expira_em < datetime.now(timezone.utc)
    resposta = api.get("/api/v1/produtos", headers=auth(token))
    assert resposta.status_code == 401 and codigo(resposta) == "NAO_AUTENTICADO"


def test_perfil_fora_da_lista_da_403(api, tokens):
    # ATENDENTE não cadastra unidade; CLIENTE não vê o catálogo de gestão
    unidade = {
        "nome": "Teste",
        "tipo_operacao": "COMPLETA",
        "cidade": "Natal",
        "uf": "RN",
        "horario_abertura": "06:00",
        "horario_fechamento": "22:00",
    }
    atendente = api.post("/api/v1/unidades", json=unidade, headers=auth(tokens["atendente_recife"]))
    cliente = api.get("/api/v1/produtos", headers=auth(tokens["maria"]))
    assert atendente.status_code == cliente.status_code == 403
    assert codigo(atendente) == codigo(cliente) == "SEM_PERMISSAO"
