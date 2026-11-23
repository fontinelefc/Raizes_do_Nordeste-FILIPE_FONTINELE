"""Views do domínio Acesso: login e cadastro de cliente (RF01, UC16)."""

from typing import Literal

from pydantic import Field

from app.models.enums import FaixaEtaria, Perfil
from app.views.comum import DataHora, Email, Entrada, Saida


class LoginEntrada(Entrada):
    email: Email
    senha: str = Field(min_length=8, max_length=72)  # 72 = limite do bcrypt
    tipo: Literal["FUNCIONARIO", "CLIENTE"]


class Token(Saida):
    access_token: str
    token_type: str = Field(default="bearer", examples=["bearer"])
    expira_em: DataHora
    perfil: Perfil | None = None  # só para FUNCIONARIO
    unidade_id: int | None = None


class ClienteEntrada(Entrada):
    nome: str = Field(min_length=2, max_length=100)
    email: Email
    telefone: str | None = Field(default=None, max_length=20)
    senha: str = Field(min_length=8, max_length=72)
    faixa_etaria: FaixaEtaria | None = None


class Cliente(Saida):
    id: int
    nome: str
    email: str
    telefone: str | None = None
    faixa_etaria: FaixaEtaria | None = None
    saldo_pontos: int
    criado_em: DataHora
