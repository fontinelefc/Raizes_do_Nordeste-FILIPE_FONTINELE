"""E15 — Testes unitários do núcleo de segurança (RF01, RF02, RF14; D42, D43, D46, D60).

Não usam o banco nem o servidor: chamam direto as funções de
``app/nucleo/seguranca.py``. Rodam mesmo com o MySQL parado.
"""

from datetime import timedelta

import jwt
import pytest

from app.models.enums import Perfil
from app.nucleo.erros import ErroDominio
from app.nucleo.seguranca import (
    ALGORITMO,
    VALIDADE_TOKEN,
    VALIDADE_TOKEN_PEDIDO,
    Credencial,
    assinar,
    conferir_assinatura,
    conferir_senha,
    gerar_hash,
    gerar_token,
    ler_token,
)

SEGREDO = "segredo-unitario-" + "0" * 40
GERENTE = Credencial(tipo="FUNCIONARIO", id=2, perfil=Perfil.GERENTE, unidade_id=1)


# ---- Senhas (bcrypt, D18) ----

def test_hash_confere_so_com_a_senha_certa():
    senha_hash = gerar_hash("Raizes@2026")
    assert senha_hash.startswith("$2b$12$")  # bcrypt custo 12 (D55)
    assert conferir_senha("Raizes@2026", senha_hash)
    assert not conferir_senha("raizes@2026", senha_hash)


def test_conta_inexistente_e_senha_longa_nao_conferem():
    # Hash nulo = e-mail sem conta; o tempo de resposta é o mesmo da senha errada (OWASP API2)
    assert not conferir_senha("Raizes@2026", None)
    assert not conferir_senha("a" * 73, gerar_hash("a" * 72))  # passa do limite de 72 bytes do bcrypt


def test_hash_de_senha_acima_de_72_bytes_e_recusado():
    with pytest.raises(ErroDominio) as erro:
        gerar_hash("ç" * 37)  # 74 bytes em UTF-8
    assert erro.value.codigo == "VALIDACAO"


# ---- JWT (D42, D46, D60) ----

def test_token_de_funcionario_leva_perfil_unidade_e_vale_60_min():
    token, expira_em = gerar_token(GERENTE, SEGREDO)
    assert ler_token(token, SEGREDO) == GERENTE
    carga = jwt.decode(token, SEGREDO, algorithms=[ALGORITMO])
    assert carga["exp"] - carga["iat"] == VALIDADE_TOKEN.total_seconds() == 3600
    assert expira_em.tzinfo is not None


def test_token_de_cliente_e_de_pedido_nao_levam_perfil():
    token, _ = gerar_token(Credencial(tipo="CLIENTE", id=1), SEGREDO)
    assert ler_token(token, SEGREDO) == Credencial(tipo="CLIENTE", id=1)
    token, _ = gerar_token(Credencial(tipo="PEDIDO", id=7), SEGREDO, VALIDADE_TOKEN_PEDIDO)
    carga = jwt.decode(token, SEGREDO, algorithms=[ALGORITMO])
    assert carga["tipo"] == "PEDIDO" and "perfil" not in carga
    assert carga["exp"] - carga["iat"] == 4 * 3600  # D46


@pytest.mark.parametrize(
    "token",
    [
        gerar_token(GERENTE, SEGREDO, timedelta(seconds=-1))[0],  # expirado
        gerar_token(GERENTE, "outro-segredo-" + "1" * 40)[0],  # outro segredo
        gerar_token(GERENTE, SEGREDO)[0][:-2] + "xx",  # assinatura adulterada
        jwt.encode({"sub": "2", "tipo": "FUNCIONARIO"}, SEGREDO, algorithm=ALGORITMO),  # sem exp e iat
        jwt.encode(  # perfil que não existe
            {"sub": "2", "tipo": "FUNCIONARIO", "perfil": "ROOT", "iat": 0, "exp": 2**40}, SEGREDO, algorithm=ALGORITMO
        ),
        "nao-e-um-jwt",
    ],
    ids=["expirado", "outro_segredo", "adulterado", "sem_exp", "perfil_invalido", "lixo"],
)
def test_token_invalido_vira_nao_autenticado(token):
    with pytest.raises(ErroDominio) as erro:
        ler_token(token, SEGREDO)
    assert erro.value.codigo == "NAO_AUTENTICADO"


def test_token_com_algoritmo_none_e_recusado():
    # Ataque clássico: token sem assinatura ("alg": "none") não pode ser aceito
    token = jwt.encode({"sub": "1", "tipo": "FUNCIONARIO", "iat": 0, "exp": 2**40}, None, algorithm="none")
    with pytest.raises(ErroDominio):
        ler_token(token, SEGREDO)


def test_sem_segredo_configurado_a_api_nao_emite_nem_le_token():
    with pytest.raises(RuntimeError):
        gerar_token(GERENTE, "")
    with pytest.raises(RuntimeError):
        ler_token("qualquer", "")


# ---- HMAC do webhook (D43) ----

def test_assinatura_e_o_hmac_sha256_do_corpo_bruto():
    corpo = b'{"evento_id":"evt_1"}'
    assinatura = assinar(corpo, "segredo")
    # Valor de referência calculado fora do Python:
    # printf '%s' '{"evento_id":"evt_1"}' | openssl dgst -sha256 -hmac segredo
    assert assinatura == "sha256=e4fc075fa80a90180d187d81095e362dc09baffd689932a152b9a9e929e106e1"
    conferir_assinatura(corpo, assinatura, "segredo")  # não lança


@pytest.mark.parametrize(
    ("corpo", "assinatura", "segredo"),
    [
        (b"{}", None, "segredo"),  # sem cabeçalho
        (b"{}", "", "segredo"),
        (b"{ }", assinar(b"{}", "segredo"), "segredo"),  # um espaço a mais muda o HMAC
        (b"{}", assinar(b"{}", "outro"), "segredo"),
        (b"{}", assinar(b"{}", "segredo").upper(), "segredo"),
        (b"{}", assinar(b"{}", ""), ""),  # segredo não configurado recusa tudo
    ],
    ids=["ausente", "vazia", "corpo_alterado", "outro_segredo", "maiusculas", "sem_segredo"],
)
def test_assinatura_que_nao_bate_vira_assinatura_invalida(corpo, assinatura, segredo):
    with pytest.raises(ErroDominio) as erro:
        conferir_assinatura(corpo, assinatura, segredo)
    assert erro.value.codigo == "ASSINATURA_INVALIDA"
