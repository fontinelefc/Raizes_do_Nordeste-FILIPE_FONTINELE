"""Segurança da API (seção 3.6.5, D42, D43, D60).

* Senhas: bcrypt (D18).
* JWT HS256 de 60 min com PyJWT (D60); o token carrega ``sub``, ``tipo``,
  ``perfil`` e ``unidade_id``, para autorizar sem consultar o banco (ADR-06).
* Autorização por função: a dependência ``exigir_perfil`` barra com 403 o
  perfil que não está na coluna "Quem acessa" da tabela 3.6.2. A checagem por
  unidade e por objeto fica nos services, que conhecem o recurso.
* Os esquemas do contrato continuam declarados com ``auto_error=False``: a
  falta de token vira 401 no formato único de erro (D41), e não o erro
  padrão do FastAPI.
* Webhook (D43): ``X-Assinatura: sha256=<hex>`` é o HMAC-SHA256 do corpo bruto
  com ``WEBHOOK_SEGREDO``, comparado em tempo constante (``hmac.compare_digest``).
* Gateway simulado (D44): ``X-Api-Key`` comparada em tempo constante com
  ``GATEWAY_CHAVE_API``.
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.models.enums import Perfil
from app.nucleo.erros import ErroDominio

ALGORITMO = "HS256"
VALIDADE_TOKEN = timedelta(minutes=60)  # D42
VALIDADE_TOKEN_PEDIDO = timedelta(hours=4)  # D46: token_pedido do pedido anônimo
CUSTO_BCRYPT = 12  # mesmo custo da carga de exemplo (D55)

bearer = HTTPBearer(
    scheme_name="bearerAuth",
    bearerFormat="JWT",
    description="JWT HS256, validade de 60 min (token de pedido anônimo, 4 h)",
    auto_error=False,
)

assinatura_webhook = APIKeyHeader(
    name="X-Assinatura",
    scheme_name="assinaturaWebhook",
    description="sha256=<HMAC-SHA256 do corpo bruto com WEBHOOK_SEGREDO>",
    auto_error=False,
)

chave_api = APIKeyHeader(name="X-Api-Key", scheme_name="chaveApi", auto_error=False)


# ---- Senhas (bcrypt) ----

def _bytes_senha(senha: str) -> bytes | None:
    dados = senha.encode("utf-8")
    return dados if len(dados) <= 72 else None  # 72 bytes = limite do bcrypt


def gerar_hash(senha: str) -> str:
    dados = _bytes_senha(senha)
    if dados is None:
        raise ErroDominio(
            "VALIDACAO",
            "Dados de entrada inválidos",
            [{"campo": "senha", "valor": None, "problema": "a senha passa de 72 bytes"}],
        )
    return bcrypt.hashpw(dados, bcrypt.gensalt(CUSTO_BCRYPT)).decode("ascii")


# Hash fixo usado quando o e-mail não existe: o tempo de resposta fica igual ao
# da senha errada, e o login não revela quem tem conta (3.6.3, OWASP API2)
_HASH_FICTICIO = bcrypt.hashpw(b"senha-ficticia", bcrypt.gensalt(CUSTO_BCRYPT))


def conferir_senha(senha: str, senha_hash: str | None) -> bool:
    dados = _bytes_senha(senha)
    if senha_hash is None or dados is None:
        bcrypt.checkpw(b"senha-ficticia", _HASH_FICTICIO)
        return False
    return bcrypt.checkpw(dados, senha_hash.encode("ascii"))


# ---- JWT ----

@dataclass(frozen=True)
class Credencial:
    """Quem está chamando, tirado do token (sem consulta ao banco, ADR-06)."""

    tipo: str  # FUNCIONARIO, CLIENTE ou PEDIDO (D46, a partir da E12)
    id: int
    perfil: Perfil | None = None
    unidade_id: int | None = None


def gerar_token(credencial: Credencial, segredo: str, validade: timedelta = VALIDADE_TOKEN) -> tuple[str, datetime]:
    if not segredo:
        raise RuntimeError("JWT_SEGREDO não configurado no .env")
    agora = datetime.now(timezone.utc).replace(microsecond=0)
    expira_em = agora + validade
    carga = {"sub": str(credencial.id), "tipo": credencial.tipo, "iat": agora, "exp": expira_em}
    if credencial.perfil is not None:
        carga["perfil"] = credencial.perfil.value
        carga["unidade_id"] = credencial.unidade_id
    return jwt.encode(carga, segredo, algorithm=ALGORITMO), expira_em


def _nao_autenticado() -> ErroDominio:
    return ErroDominio("NAO_AUTENTICADO", "Token ausente, inválido ou expirado")


def ler_token(token: str, segredo: str) -> Credencial:
    if not segredo:
        raise RuntimeError("JWT_SEGREDO não configurado no .env")
    try:
        carga = jwt.decode(
            token, segredo, algorithms=[ALGORITMO], options={"require": ["sub", "tipo", "exp", "iat"]}
        )
        perfil = Perfil(carga["perfil"]) if carga.get("perfil") else None
        return Credencial(tipo=carga["tipo"], id=int(carga["sub"]), perfil=perfil, unidade_id=carga.get("unidade_id"))
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise _nao_autenticado() from None


# ---- Dependências do FastAPI ----

def exigir_token(
    request: Request, credenciais: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> Credencial:
    """401 NAO_AUTENTICADO sem token válido."""
    if credenciais is None:
        raise _nao_autenticado()
    return ler_token(credenciais.credentials, request.app.state.config.jwt_segredo)


def credencial_opcional(
    request: Request, credenciais: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> Credencial | None:
    """Login opcional (criação de pedido, D12): sem token = anônimo; token inválido = 401."""
    if credenciais is None:
        return None
    return ler_token(credenciais.credentials, request.app.state.config.jwt_segredo)


def exigir_cliente(credencial: Annotated[Credencial, Depends(exigir_token)]) -> Credencial:
    """Rotas /clientes/me: token de funcionário ou token_pedido não identifica um cliente (401, D75)."""
    if credencial.tipo != "CLIENTE":
        raise ErroDominio("NAO_AUTENTICADO", "Esta rota exige o login de um cliente")
    return credencial


def exigir_perfil(*perfis: Perfil):
    """Autorização por função (nível 1 da 3.6.5): 403 para outro perfil ou para não funcionário."""

    def dependencia(credencial: Annotated[Credencial, Depends(exigir_token)]) -> Credencial:
        if credencial.tipo != "FUNCIONARIO" or credencial.perfil not in perfis:
            raise ErroDominio("SEM_PERMISSAO", "Perfil sem acesso a esta operação")
        return credencial

    return dependencia


# ---- Webhook (HMAC, D43) e chave do gateway simulado (D44) ----

def assinar(corpo: bytes, segredo: str) -> str:
    """Valor do cabeçalho X-Assinatura para um corpo; usado também pelo gateway simulado."""
    return "sha256=" + hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()


def conferir_assinatura(corpo: bytes, assinatura: str | None, segredo: str) -> None:
    """401 ASSINATURA_INVALIDA se a assinatura faltar, não bater ou o segredo não estiver configurado."""
    if not segredo or not assinatura or not hmac.compare_digest(assinar(corpo, segredo), assinatura):
        raise ErroDominio("ASSINATURA_INVALIDA", "Assinatura do webhook ausente ou inválida")


async def corpo_assinado(
    request: Request, assinatura: Annotated[str | None, Depends(assinatura_webhook)]
) -> bytes:
    """Dependência do webhook: confere o HMAC sobre o corpo bruto, antes de validar o JSON.

    O HMAC vale para os bytes recebidos; reconverter o JSON mudaria espaços e a
    ordem das chaves, e a assinatura deixaria de bater.
    """
    corpo = await request.body()
    conferir_assinatura(corpo, assinatura, request.app.state.config.webhook_segredo)
    return corpo


def exigir_chave_api(request: Request, chave: Annotated[str | None, Depends(chave_api)]) -> None:
    """Rotas do gateway simulado: 401 NAO_AUTENTICADO sem a chave certa."""
    esperada = request.app.state.config.gateway_chave_api
    if not esperada or not chave or not hmac.compare_digest(esperada.encode("utf-8"), chave.encode("utf-8")):
        raise ErroDominio("NAO_AUTENTICADO", "Chave de API ausente ou inválida")
