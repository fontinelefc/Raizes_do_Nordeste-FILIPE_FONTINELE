"""Conexão com o MySQL (D18, D55, D61, D62).

* Um engine por configuração, criado só no primeiro uso: a aplicação sobe e o
  teste de contrato roda mesmo sem banco.
* Cada conexão é aberta com ``time_zone = '+00:00'``, porque as datas são
  gravadas em UTC (M12, D55).
* A sessão vale por requisição. Quem confirma a transação é o service chamado
  pelo controller (D52-5); a sessão só é fechada aqui.
"""

from collections.abc import Iterator
from functools import lru_cache

from fastapi import Request
from sqlalchemy import Engine, URL, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.nucleo.config import Config


@lru_cache(maxsize=4)
def obter_engine(config: Config) -> Engine:
    url = URL.create(
        "mysql+pymysql",
        username=config.db_usuario,
        password=config.db_senha,
        host=config.db_host,
        port=config.db_porta,
        database=config.db_nome,
        query={"charset": "utf8mb4"},
    )
    return create_engine(
        url,
        pool_pre_ping=True,  # descarta conexão que o MySQL fechou
        pool_recycle=3600,
        connect_args={"init_command": "SET time_zone = '+00:00'", "connect_timeout": 5},
    )


@lru_cache(maxsize=4)
def _fabrica(config: Config) -> sessionmaker[Session]:
    return sessionmaker(obter_engine(config), expire_on_commit=False)


def obter_sessao(request: Request) -> Iterator[Session]:
    """Dependência do FastAPI: uma sessão por requisição."""
    sessao = _fabrica(request.app.state.config)()
    try:
        yield sessao
    finally:
        sessao.close()


def abrir_sessao(config: Config) -> Session:
    """Sessão fora de uma requisição, para a tarefa de expiração (D71); quem abre, fecha."""
    return _fabrica(config)()


def testar_conexao(config: Config) -> None:
    """Executa ``SELECT 1``; lança a exceção do driver se o banco não responder."""
    with obter_engine(config).connect() as conexao:
        conexao.execute(text("SELECT 1"))
