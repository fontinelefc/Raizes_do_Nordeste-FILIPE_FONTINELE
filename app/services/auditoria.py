"""AuditoriaService: trilha das operações sensíveis (RF25; RN13; ADR-07; D29, D65).

Dono da tabela ``registro_auditoria``, que só recebe INSERT (D57). Não tem
controller: os outros services o chamam na mesma sessão, e o registro entra na
mesma transação da operação auditada (ADR-07). Se a operação for desfeita, o
registro também é; se o registro falhar, a operação não acontece.

Regra de transação (D52-5): este service nunca faz COMMIT.

LGPD (RN18): ``detalhes`` guarda só o que mudou (antes e depois), nunca nome,
e-mail, telefone, senha ou token. O titular fica identificado por ``ator_id`` e
``entidade_id``.

Ações registradas na E14:

* Fidelidade e LGPD: LER_DADOS_CLIENTE, LER_CONSENTIMENTOS,
  CONCEDER_CONSENTIMENTO, REVOGAR_CONSENTIMENTO.
* Pedidos e pagamentos: CANCELAR_PEDIDO, CONFIRMAR_PAGAMENTO_BALCAO (D14),
  ESTORNO_AUTOMATICO (aprovação tardia, D24).
* Unidades e catálogo (D65): CADASTRAR_UNIDADE, ALTERAR_UNIDADE,
  CADASTRAR_PRODUTO, ALTERAR_PRODUTO, DEFINIR_ITEM_CARDAPIO.
"""

import json

from sqlalchemy.orm import Session

from app.models.enums import OrigemAcao
from app.models.registro_auditoria import RegistroAuditoria
from app.nucleo.seguranca import Credencial

# Tipo do token → quem aparece como ator. O token_pedido (D46) é de um cliente anônimo: sem id.
ATOR_DO_TOKEN = {"FUNCIONARIO": OrigemAcao.FUNCIONARIO, "CLIENTE": OrigemAcao.CLIENTE, "PEDIDO": OrigemAcao.CLIENTE}


def _json(detalhes: dict | None) -> dict | None:
    """Decimal, time, datetime e enumerações viram texto, como na API."""
    if detalhes is None:
        return None
    return json.loads(json.dumps(detalhes, default=lambda valor: getattr(valor, "value", str(valor))))


class AuditoriaService:
    def __init__(self, sessao: Session) -> None:
        self.sessao = sessao

    def registrar(
        self,
        acao: str,
        entidade: str,
        entidade_id: int | None,
        *,
        ator: Credencial | None = None,
        origem: OrigemAcao | None = None,
        unidade_id: int | None = None,
        detalhes: dict | None = None,
        ip: str | None = None,
    ) -> None:
        """Grava um registro. Quem agiu vem do token (``ator``) ou, sem token, de ``origem`` (SISTEMA, GATEWAY)."""
        if ator is not None:
            ator_tipo = ATOR_DO_TOKEN[ator.tipo]
            ator_id = None if ator.tipo == "PEDIDO" else ator.id
        else:
            ator_tipo, ator_id = origem or OrigemAcao.SISTEMA, None
        self.sessao.add(
            RegistroAuditoria(
                ator_tipo=ator_tipo,
                ator_id=ator_id,
                acao=acao,
                entidade=entidade,
                entidade_id=entidade_id,
                unidade_id=unidade_id,
                detalhes=_json(detalhes),
                ip_origem=ip,
            )
        )
        self.sessao.flush()
