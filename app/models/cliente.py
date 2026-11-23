"""Tabela ``cliente`` (RF01, RF17, RF20; RN17). Service dono: FidelidadeService (D52-7)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, FetchedValue, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_mysql
from app.models.enums import FaixaEtaria


class Cliente(Base):
    __tablename__ = "cliente"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(150), unique=True)
    telefone: Mapped[str | None] = mapped_column(String(20))
    senha_hash: Mapped[str] = mapped_column(String(255))
    faixa_etaria: Mapped[FaixaEtaria | None] = mapped_column(enum_mysql(FaixaEtaria))
    saldo_pontos: Mapped[int] = mapped_column(Integer, server_default=FetchedValue())
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
