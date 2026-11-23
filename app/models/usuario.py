"""Tabela ``usuario`` (funcionários; RF01, RF02; RN12). Service dono: AcessoService."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, FetchedValue, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_mysql
from app.models.enums import Perfil


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    unidade_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("unidade.id"))
    nome: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(150), unique=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    perfil: Mapped[Perfil] = mapped_column(enum_mysql(Perfil))
    ativo: Mapped[bool] = mapped_column(Boolean, server_default=FetchedValue())
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
