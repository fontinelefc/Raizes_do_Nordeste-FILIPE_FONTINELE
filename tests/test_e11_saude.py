"""E11 — Health check e formato dos erros (RNF10, D38, D40, D62)."""

from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import criar_app
from tests.apoio import codigo


def test_health_com_banco_no_ar_da_200(api):
    resposta = api.get("/api/v1/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok", "banco": "ok"}


def test_health_com_banco_fora_do_ar_da_503(config):
    # Porta 1: nenhum MySQL escuta ali, a conexão é recusada na hora
    with TestClient(criar_app(replace(config, db_porta=1))) as cliente:
        resposta = cliente.get("/api/v1/health")
    assert resposta.status_code == 503 and codigo(resposta) == "BANCO_INDISPONIVEL"


def test_rota_de_negocio_com_banco_fora_do_ar_da_503(config):
    with TestClient(criar_app(replace(config, db_porta=1))) as cliente:
        resposta = cliente.get("/api/v1/unidades")
    assert resposta.status_code == 503 and codigo(resposta) == "BANCO_INDISPONIVEL"


def test_x_request_id_volta_na_resposta_e_no_erro(api):
    # D40: o id enviado pelo canal volta no cabeçalho e no corpo do erro
    resposta = api.get("/api/v1/unidades/999/cardapio", headers={"X-Request-ID": "teste-123"})
    assert resposta.headers["X-Request-ID"] == "teste-123"
    assert resposta.json()["erro"]["request_id"] == "teste-123"
