"""E17 — Cabeçalho Retry-After nas respostas 503 (resposta Indisponivel do contrato).

O valor é fixo (RETRY_AFTER_SEGUNDOS, 10 s) e vale para os dois códigos 503:
GATEWAY_INDISPONIVEL e BANCO_INDISPONIVEL. Os outros erros não mandam o cabeçalho.
"""

from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import criar_app
from app.nucleo.cliente_gateway import ClienteGateway
from app.nucleo.erros import RETRY_AFTER_SEGUNDOS
from tests.apoio import codigo, criar_pedido, pagar_online


def test_valor_do_retry_after_e_10_segundos():
    assert RETRY_AFTER_SEGUNDOS == 10


def test_health_com_banco_fora_do_ar_manda_retry_after(config):
    # Porta 1: nenhum MySQL escuta ali (mesmo recurso do test_e11_saude)
    with TestClient(criar_app(replace(config, db_porta=1))) as cliente:
        resposta = cliente.get("/api/v1/health")
    assert resposta.status_code == 503 and codigo(resposta) == "BANCO_INDISPONIVEL"
    assert resposta.headers["Retry-After"] == "10"


def test_rota_de_negocio_com_banco_fora_do_ar_manda_retry_after(config):
    with TestClient(criar_app(replace(config, db_porta=1))) as cliente:
        resposta = cliente.get("/api/v1/unidades")
    assert resposta.status_code == 503 and codigo(resposta) == "BANCO_INDISPONIVEL"
    assert resposta.headers["Retry-After"] == "10"


def test_gateway_fora_do_ar_manda_retry_after(api):
    pedido = criar_pedido(api)
    api.app.state.cliente_gateway = ClienteGateway(None)  # sem gateway (D72)
    resposta = pagar_online(api, pedido["id"], pedido["token_pedido"])
    assert resposta.status_code == 503 and codigo(resposta) == "GATEWAY_INDISPONIVEL"
    assert resposta.headers["Retry-After"] == "10"


def test_erro_que_nao_e_503_nao_manda_retry_after(config):
    with TestClient(criar_app(config)) as cliente:
        validacao = cliente.get("/api/v1/unidades", params={"limit": 500})
        sem_token = cliente.get("/api/v1/clientes/me")
    assert validacao.status_code == 422 and "Retry-After" not in validacao.headers
    assert sem_token.status_code == 401 and "Retry-After" not in sem_token.headers
