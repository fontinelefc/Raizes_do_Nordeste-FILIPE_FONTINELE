"""Parâmetros e dependências comuns às rotas (components/parameters, D53)."""

from typing import Annotated

from fastapi import Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.models.enums import Perfil
from app.nucleo.banco import obter_sessao
from app.nucleo.seguranca import (
    Credencial,
    corpo_assinado,
    credencial_opcional,
    exigir_cliente,
    exigir_perfil,
    exigir_token,
)

Id = Annotated[int, Path(ge=1)]
ProdutoId = Annotated[int, Path(ge=1)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]

# Uma sessão do banco por requisição (D52-5)
Sessao = Annotated[Session, Depends(obter_sessao)]


# Autorização por função (3.6.5, nível 1): perfis da coluna "Quem acessa" da tabela 3.6.2
SO_MATRIZ = Annotated[Credencial, Depends(exigir_perfil(Perfil.MATRIZ))]
MATRIZ_OU_GERENTE = Annotated[Credencial, Depends(exigir_perfil(Perfil.MATRIZ, Perfil.GERENTE))]
SO_ATENDENTE = Annotated[Credencial, Depends(exigir_perfil(Perfil.ATENDENTE))]

# Qualquer token válido (funcionário, cliente ou token_pedido); o service decide o resto (níveis 2 e 3)
TOKEN = Annotated[Credencial, Depends(exigir_token)]
# Rotas /clientes/me (D42): só token de CLIENTE; outro tipo responde 401 (D75)
SO_CLIENTE = Annotated[Credencial, Depends(exigir_cliente)]
# Login opcional: None = pedido anônimo (D12, D46)
TOKEN_OPCIONAL = Annotated[Credencial | None, Depends(credencial_opcional)]

# Webhook (D43): corpo bruto com o HMAC já conferido (401 ASSINATURA_INVALIDA antes de validar o JSON)
CORPO_ASSINADO = Annotated[bytes, Depends(corpo_assinado)]


def ip_origem(request: Request) -> str | None:
    """IP de quem chamou, para a auditoria (RF25). Atrás do balanceador, viria do X-Forwarded-For (evolução)."""
    return request.client.host if request.client else None


IP = Annotated[str | None, Depends(ip_origem)]
