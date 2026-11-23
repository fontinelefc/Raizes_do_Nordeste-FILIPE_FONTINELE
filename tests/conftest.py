"""Apoio aos testes de integração (D64).

Os testes usam o MySQL de verdade, com a carga de exemplo do
``sql/03_dados_exemplo.sql``, e as credenciais do ``.env``.

Cada teste roda dentro de uma transação que é desfeita no fim (D57: o usuário
``raizes_app`` não tem DELETE). O COMMIT feito pelos services vira um SAVEPOINT,
então o banco volta ao estado da carga depois de cada teste.

O teste de contrato (``test_contrato_openapi.py``) não usa nada daqui e roda
sem banco.
"""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.main import criar_app
from app.nucleo.banco import obter_engine, obter_sessao, testar_conexao
from app.nucleo.config import Config, carregar_config
from tests.apoio import CLIENTES, FUNCIONARIOS, SENHA_EXEMPLO



@pytest.fixture(scope="session")
def config() -> Config:
    cfg = carregar_config()
    # Permite rodar os testes sem os segredos no .env; a tarefa de expiração fica
    # desligada (os testes chamam a expiração direto, D71) e o gateway simulado ligado
    cfg = replace(
        cfg,
        jwt_segredo=cfg.jwt_segredo or "segredo-so-para-testes-" + "0" * 40,
        webhook_segredo=cfg.webhook_segredo or "webhook-so-para-testes-" + "0" * 40,
        gateway_chave_api=cfg.gateway_chave_api or "chave-so-para-testes-" + "0" * 40,
        gateway_simulado=True,
        expiracao_intervalo=0,
    )
    try:
        testar_conexao(cfg)
    except SQLAlchemyError as exc:
        pytest.fail(
            "MySQL indisponível para os testes de integração. Confira DB_HOST, DB_PORTA, "
            f"DB_USUARIO e DB_SENHA no .env e rode os scripts sql/01 a 03. Erro: {exc.orig or exc}",
            pytrace=False,
        )
    return cfg


@pytest.fixture
def sessao(config: Config) -> Iterator[Session]:
    """Sessão presa a uma transação externa que é desfeita no fim do teste."""
    conexao = obter_engine(config).connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


@pytest.fixture
def api(config: Config, sessao: Session) -> Iterator[TestClient]:
    app = criar_app(config)

    def sessao_do_teste():
        yield sessao

    app.dependency_overrides[obter_sessao] = sessao_do_teste
    with TestClient(app) as cliente:
        yield cliente


@pytest.fixture(scope="session")
def tokens(config: Config) -> dict[str, str]:
    """Um token por conta de exemplo; o login só lê o banco."""
    resultado = {}
    with TestClient(criar_app(config)) as cliente:
        for nome, email in FUNCIONARIOS.items():
            resultado[nome] = _login(cliente, email, "FUNCIONARIO")
        for nome, email in CLIENTES.items():
            resultado[nome] = _login(cliente, email, "CLIENTE")
    return resultado


def _login(cliente: TestClient, email: str, tipo: str) -> str:
    resposta = cliente.post("/api/v1/auth/login", json={"email": email, "senha": SENHA_EXEMPLO, "tipo": tipo})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()["access_token"]
