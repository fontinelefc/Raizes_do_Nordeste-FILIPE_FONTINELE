"""Tabela ``unidade`` (RF03; RN02, RN05, RN12). Service dono: UnidadeService."""

from datetime import datetime, time

from sqlalchemy import BigInteger, Boolean, DateTime, FetchedValue, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_mysql
from app.models.enums import TipoOperacao


class Unidade(Base):
    __tablename__ = "unidade"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(100))
    tipo_operacao: Mapped[TipoOperacao] = mapped_column(enum_mysql(TipoOperacao))
    cidade: Mapped[str] = mapped_column(String(80))
    uf: Mapped[str] = mapped_column(String(2))
    horario_abertura: Mapped[time] = mapped_column(Time)
    horario_fechamento: Mapped[time] = mapped_column(Time)
    ativa: Mapped[bool] = mapped_column(Boolean, server_default=FetchedValue())
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
