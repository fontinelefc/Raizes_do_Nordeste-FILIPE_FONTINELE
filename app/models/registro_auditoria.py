"""Tabela ``registro_auditoria`` (RF25; RN13; M10/D29: sem FK e somente inserção). Service dono: AuditoriaService.

O usuário ``raizes_app`` só tem SELECT e INSERT nesta tabela (D57): a aplicação
não consegue alterar nem apagar a trilha.
"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, FetchedValue, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_mysql
from app.models.enums import OrigemAcao


class RegistroAuditoria(Base):
    __tablename__ = "registro_auditoria"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ator_tipo: Mapped[OrigemAcao] = mapped_column(enum_mysql(OrigemAcao))
    ator_id: Mapped[int | None] = mapped_column(BigInteger)  # NULL para SISTEMA, GATEWAY e pedido anônimo
    acao: Mapped[str] = mapped_column(String(50))
    entidade: Mapped[str] = mapped_column(String(50))
    entidade_id: Mapped[int | None] = mapped_column(BigInteger)
    unidade_id: Mapped[int | None] = mapped_column(BigInteger)
    detalhes: Mapped[dict | None] = mapped_column(JSON)  # antes e depois, sem dados pessoais
    ip_origem: Mapped[str | None] = mapped_column(String(45))
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
