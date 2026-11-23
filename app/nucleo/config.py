"""Configuração lida de variáveis de ambiente (segredos fora do código, PLANO 8).

Se existir um arquivo ``.env`` na raiz do projeto, as linhas ``CHAVE=valor``
são carregadas sem sobrescrever variáveis já definidas no sistema. O leitor é
simples de propósito, para não acrescentar dependência (D18).
"""

import os
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def _carregar_env(arquivo: Path = RAIZ / ".env") -> None:
    if not arquivo.is_file():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip("\"'"))


def _booleano(valor: str) -> bool:
    return valor.strip().lower() in {"1", "true", "sim", "yes"}


@dataclass(frozen=True)
class Config:
    # D44: os endpoints do gateway simulado só existem com GATEWAY_SIMULADO=true
    gateway_simulado: bool = False
    # Banco de dados (D55): mesmo usuário e senha do sql/02_usuario_app.sql
    db_host: str = "127.0.0.1"
    db_porta: int = 3306
    db_nome: str = "raizes_nordeste"
    db_usuario: str = "raizes_app"
    db_senha: str = ""
    # Segredo do JWT (D42, D60); vazio impede a emissão e a validação de tokens
    jwt_segredo: str = ""
    # Segredo do HMAC do webhook (D43) e chave das rotas do gateway simulado (D44);
    # vazios, o webhook e as rotas do gateway recusam toda chamada com 401
    webhook_segredo: str = ""
    gateway_chave_api: str = ""
    # D71: intervalo, em segundos, da tarefa que expira pedidos sem pagamento (T4); 0 desliga
    expiracao_intervalo: int = 60


def carregar_config() -> Config:
    _carregar_env()
    return Config(
        gateway_simulado=_booleano(os.getenv("GATEWAY_SIMULADO", "false")),
        db_host=os.getenv("DB_HOST", "127.0.0.1"),
        db_porta=int(os.getenv("DB_PORTA", "3306")),
        db_nome=os.getenv("DB_NOME", "raizes_nordeste"),
        db_usuario=os.getenv("DB_USUARIO", "raizes_app"),
        db_senha=os.getenv("DB_SENHA", ""),
        jwt_segredo=os.getenv("JWT_SEGREDO", ""),
        webhook_segredo=os.getenv("WEBHOOK_SEGREDO", ""),
        gateway_chave_api=os.getenv("GATEWAY_CHAVE_API", ""),
        expiracao_intervalo=int(os.getenv("EXPIRACAO_INTERVALO", "60")),
    )
