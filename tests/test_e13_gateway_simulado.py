"""E13 — Gateway simulado (rotas 26–28; D39, D44, D72, D73).

As cobranças ficam na memória da aplicação (D73); cada teste cria uma
aplicação nova, então começa com o gateway vazio.
"""

from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import criar_app
from tests.apoio import chave_gateway, codigo, decidir

BASE = "/api/v1/gateway-simulado"
COBRANCA = {"referencia": "123", "valor": "43.30", "forma": "PIX"}


def test_rotas_do_gateway_exigem_a_chave_de_api(api):
    sem = api.post(f"{BASE}/cobrancas", json=COBRANCA)
    assert sem.status_code == 401 and codigo(sem) == "NAO_AUTENTICADO"
    errada = api.post(f"{BASE}/cobrancas", json=COBRANCA, headers={"X-Api-Key": "chave-errada"})
    assert errada.status_code == 401 and codigo(errada) == "NAO_AUTENTICADO"


def test_mesma_referencia_devolve_a_mesma_transacao(api, config):
    criada = api.post(f"{BASE}/cobrancas", json=COBRANCA, headers=chave_gateway(config))
    assert criada.status_code == 201
    assert criada.json()["status"] == "PENDENTE" and criada.json()["referencia"] == "123"
    mesma = api.post(f"{BASE}/cobrancas", json=COBRANCA, headers=chave_gateway(config))
    assert mesma.status_code == 200 and mesma.json() == criada.json()  # D39
    invalida = api.post(f"{BASE}/cobrancas", json={**COBRANCA, "valor": "43,30"}, headers=chave_gateway(config))
    assert invalida.status_code == 422 and codigo(invalida) == "VALIDACAO"


def test_decidir_ou_estornar_cobranca_inexistente_ou_fora_do_estado(api, config):
    inexistente = decidir(api, config, "sim_naoexiste", "APROVADO")
    assert inexistente.status_code == 404 and codigo(inexistente) == "TRANSACAO_DESCONHECIDA"
    transacao = api.post(f"{BASE}/cobrancas", json=COBRANCA, headers=chave_gateway(config)).json()["transacao_id"]

    pendente = api.post(f"{BASE}/estornos", json={"transacao_id": transacao}, headers=chave_gateway(config))
    assert pendente.status_code == 409 and codigo(pendente) == "TRANSICAO_INVALIDA"  # só estorna o aprovado

    # Sem pagamento correspondente na API, o webhook entregue em segundo plano só vai para o log
    assert decidir(api, config, transacao, "APROVADO").status_code == 202
    de_novo = decidir(api, config, transacao, "RECUSADO")
    assert de_novo.status_code == 409 and codigo(de_novo) == "TRANSICAO_INVALIDA"
    estorno = api.post(f"{BASE}/estornos", json={"transacao_id": transacao}, headers=chave_gateway(config))
    assert estorno.status_code == 202
    sem_cobranca = api.post(f"{BASE}/estornos", json={"transacao_id": "sim_naoexiste"}, headers=chave_gateway(config))
    assert sem_cobranca.status_code == 404 and codigo(sem_cobranca) == "TRANSACAO_DESCONHECIDA"


def test_sem_gateway_simulado_as_rotas_nao_existem(config):
    """D44: com GATEWAY_SIMULADO=false, o router do gateway não é incluído."""
    with TestClient(criar_app(replace(config, gateway_simulado=False))) as cliente:
        resposta = cliente.post(f"{BASE}/cobrancas", json=COBRANCA, headers=chave_gateway(config))
    assert resposta.status_code == 404 and codigo(resposta) == "NAO_ENCONTRADO"
