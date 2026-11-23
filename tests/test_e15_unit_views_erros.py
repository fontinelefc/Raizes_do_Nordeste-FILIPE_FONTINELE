"""E15 — Testes unitários das views e do formato único de erro (seção 3.6.1, 3.6.4; D40, D41, D53).

As views são testadas direto pelo Pydantic. Os erros 404 e 500 usam uma
aplicação criada com uma configuração em memória: nenhuma rota usada aqui abre
conexão com o banco, então estes testes rodam com o MySQL parado.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from app.main import PREFIXO, criar_app
from app.nucleo.config import Config
from app.nucleo.erros import STATUS_POR_CODIGO
from app.views.comum import DataHora, Dinheiro, Email, Saida
from app.views.pagamentos import EventoWebhook, PagamentoOnlineEntrada
from app.views.pedidos import CancelamentoEntrada, PedidoEntrada

RAIZ_APP = Path(__file__).resolve().parents[1] / "app"


# ---- Dinheiro, e-mail e data (3.6.1) ----

@pytest.mark.parametrize("valor", ["0.00", "18.90", "99999999.99"])
def test_dinheiro_aceita_texto_com_duas_casas(valor):
    assert TypeAdapter(Dinheiro).validate_python(valor) == valor


@pytest.mark.parametrize("valor", ["18.9", "18", "18,90", "-1.00", "1.000", "123456789.00", 18.90])
def test_dinheiro_recusa_outro_formato_e_float(valor):
    with pytest.raises(ValidationError):
        TypeAdapter(Dinheiro).validate_python(valor)


@pytest.mark.parametrize(("valor", "valido"), [("maria@cliente.example", True), ("sem-arroba", False), ("a b@c.d", False), ("a@b", False)])
def test_email_validado_por_padrao_simples(valor, valido):
    adaptador = TypeAdapter(Email)
    if valido:
        assert adaptador.validate_python(valor) == valor
    else:
        with pytest.raises(ValidationError):
            adaptador.validate_python(valor)


class _ComData(Saida):
    quando: DataHora


def test_data_sem_fuso_do_banco_sai_em_utc_com_z():
    # O MySQL devolve DATETIME sem fuso, já em UTC (M12, D55)
    assert _ComData(quando=datetime(2026, 11, 23, 15, 0)).model_dump_json() == '{"quando":"2026-11-23T15:00:00Z"}'


def test_data_com_outro_fuso_e_convertida_para_utc():
    recife = datetime(2026, 11, 23, 12, 0, tzinfo=timezone(timedelta(hours=-3)))
    assert _ComData(quando=recife).model_dump_json() == '{"quando":"2026-11-23T15:00:00Z"}'


# ---- Corpos de entrada (D40, OWASP API3) ----

@pytest.mark.parametrize(
    ("view", "corpo"),
    [
        (PagamentoOnlineEntrada, {"forma": "PIX", "valor": "1.00"}),
        (PedidoEntrada, {"unidade_id": 1, "canal": "APP", "itens": [{"produto_id": 1, "quantidade": 1}], "status": "PAGO"}),
        (PedidoEntrada, {"unidade_id": 1, "canal": "APP", "itens": [{"produto_id": 1, "quantidade": 1, "preco": "0.01"}]}),
        (PedidoEntrada, {"unidade_id": 1, "canal": "APP", "itens": [], "cliente_id": 2}),
    ],
    ids=["valor_no_pagamento", "status_no_pedido", "preco_no_item", "cliente_id_no_pedido"],
)
def test_campo_extra_no_corpo_e_recusado(view, corpo):
    with pytest.raises(ValidationError) as erro:
        view.model_validate(corpo)
    assert any(e["type"] == "extra_forbidden" for e in erro.value.errors())


def test_limites_do_pedido_e_da_justificativa():
    item = {"produto_id": 1, "quantidade": 1}
    PedidoEntrada.model_validate({"unidade_id": 1, "canal": "APP", "itens": [item] * 20})
    for corpo in (
        {"unidade_id": 1, "canal": "APP", "itens": []},  # sem itens
        {"unidade_id": 1, "canal": "APP", "itens": [item] * 21},  # mais de 20 itens
        {"unidade_id": 1, "canal": "APP", "itens": [{"produto_id": 1, "quantidade": 21}]},
        {"unidade_id": 1, "canal": "DELIVERY", "itens": [item]},  # canal que não existe
    ):
        with pytest.raises(ValidationError):
            PedidoEntrada.model_validate(corpo)
    with pytest.raises(ValidationError):
        CancelamentoEntrada.model_validate({"justificativa": "curta"})  # RF12: 10 caracteres ou mais


def test_pagamento_online_nao_aceita_dinheiro():
    with pytest.raises(ValidationError):
        PagamentoOnlineEntrada.model_validate({"forma": "DINHEIRO"})  # D14: dinheiro só no balcão


def test_evento_do_webhook_exige_tipo_e_status_conhecidos():
    base = {"evento_id": "evt_1", "transacao_id": "sim_1", "referencia": "1", "ocorrido_em": "2026-11-23T15:00:00Z"}
    evento = EventoWebhook.model_validate({**base, "tipo": "payment.approved", "status": "APROVADO"})
    assert evento.ocorrido_em.tzinfo == timezone.utc
    with pytest.raises(ValidationError):
        EventoWebhook.model_validate({**base, "tipo": "payment.pending", "status": "APROVADO"})


# ---- Catálogo de códigos (3.6.4, D41, ERR-007) ----

def _codigos_lancados_no_codigo() -> set[str]:
    padrao = re.compile(r'ErroDominio\(\s*"([A-Z_]+)"')
    return {c for arquivo in RAIZ_APP.rglob("*.py") for c in padrao.findall(arquivo.read_text(encoding="utf-8"))}


def test_todo_codigo_lancado_tem_status_na_tabela():
    # Sem isso, um código novo esquecido na tabela sairia como 500 (STATUS_POR_CODIGO.get(..., 500))
    lancados = _codigos_lancados_no_codigo()
    assert len(lancados) >= 15
    assert lancados <= STATUS_POR_CODIGO.keys(), lancados - STATUS_POR_CODIGO.keys()


def test_status_dos_codigos_segue_a_regra_422_e_409():
    # D41: 422 = valor inválido por si só; 409 = conflito com o estado atual
    assert {c for c, s in STATUS_POR_CODIGO.items() if s == 422} == {
        "VALIDACAO",
        "PRECO_FORA_DA_FAIXA",
        "JUSTIFICATIVA_OBRIGATORIA",
        "AUTORIZACAO_RESPONSAVEL_OBRIGATORIA",
    }
    assert {c for c, s in STATUS_POR_CODIGO.items() if s == 409} == {
        "EMAIL_JA_CADASTRADO",
        "CODIGO_JA_CADASTRADO",
        "PRODUTO_INCOMPATIVEL_UNIDADE",
        "UNIDADE_FECHADA",
        "ITEM_INDISPONIVEL",
        "ESTOQUE_INSUFICIENTE",
        "TRANSICAO_INVALIDA",
        "PEDIDO_NAO_PAGAVEL",
        "CONSENTIMENTO_VIGENTE",
    }


# ---- 404 de rota e 500 sem pilha (3.6.4) ----

@pytest.fixture
def app_sem_banco():
    # Porta 1: nenhum MySQL escuta ali; se alguma destas rotas tocasse o banco, o teste daria 503
    config = Config(db_porta=1, jwt_segredo="segredo-unitario-" + "0" * 40, expiracao_intervalo=0)
    app = criar_app(config)

    @app.get(PREFIXO + "/teste-falha-inesperada", include_in_schema=False)
    def falha():
        raise RuntimeError("detalhe interno que não pode vazar: senha=xyz")

    return app


def test_rota_inexistente_responde_404_no_formato_unico(app_sem_banco):
    with TestClient(app_sem_banco) as cliente:
        resposta = cliente.get(PREFIXO + "/nao-existe", headers={"X-Request-ID": "req-404"})
    assert resposta.status_code == 404
    assert resposta.json()["erro"]["codigo"] == "NAO_ENCONTRADO"
    assert resposta.json()["erro"]["request_id"] == "req-404"


def test_falha_inesperada_responde_500_sem_pilha_e_com_request_id(app_sem_banco):
    with TestClient(app_sem_banco, raise_server_exceptions=False) as cliente:
        resposta = cliente.get(PREFIXO + "/teste-falha-inesperada", headers={"X-Request-ID": "req-500"})
    assert resposta.status_code == 500
    corpo = resposta.json()
    assert corpo == {"erro": {"codigo": "ERRO_INTERNO", "mensagem": "Erro interno", "request_id": "req-500"}}
    assert "senha" not in resposta.text and "Traceback" not in resposta.text and "RuntimeError" not in resposta.text
    assert resposta.headers["X-Request-ID"] == "req-500"


def test_rota_protegida_sem_banco_e_sem_token_ja_responde_401(app_sem_banco):
    # A autenticação vem antes de qualquer acesso ao banco
    with TestClient(app_sem_banco) as cliente:
        resposta = cliente.get(PREFIXO + "/clientes/me")
    assert resposta.status_code == 401 and resposta.json()["erro"]["codigo"] == "NAO_AUTENTICADO"
