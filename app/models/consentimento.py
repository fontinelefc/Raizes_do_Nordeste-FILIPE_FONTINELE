"""Tabela ``consentimento`` (RF20; RN16, RN17; M09: cada aceite é uma nova linha). Service dono: FidelidadeService."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, FetchedValue, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_mysql
from app.models.enums import Finalidade


class Consentimento(Base):
    __tablename__ = "consentimento"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("cliente.id"))
    finalidade: Mapped[Finalidade] = mapped_column(enum_mysql(Finalidade))
    versao_termo: Mapped[str] = mapped_column(String(10))
    autorizado_responsavel: Mapped[bool] = mapped_column(Boolean)
    concedido_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
    revogado_em: Mapped[datetime | None] = mapped_column(DateTime)  # NULL = vigente
