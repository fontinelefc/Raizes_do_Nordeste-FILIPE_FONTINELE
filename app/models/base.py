"""Base declarativa do SQLAlchemy (D18, D52-3).

O esquema é criado pelo script ``sql/01_esquema.sql`` (D18, sem Alembic): os
models só mapeiam as tabelas e nunca criam nem alteram estrutura.
"""

from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def enum_mysql(tipo):
    """Mapeia uma enumeração Python para a coluna ENUM do MySQL pelo valor."""
    return SAEnum(tipo, values_callable=lambda e: [item.value for item in e], native_enum=True)
