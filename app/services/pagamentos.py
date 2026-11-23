"""PagamentoService: pagamento online, no balcão, webhook e estorno (RF13, RF14; RN09; D14, D24, D33, D39, D43).

Dono das tabelas ``pagamento`` e ``evento_pagamento``. Lê e muda o pedido só
pelo PedidoService (T2, T3), que por sua vez mexe no estoque pelo EstoqueService
(D52-7). Quando é chamado pelo controller, faz o COMMIT (D52-5); quando é chamado
pelo PedidoService (cancelamento, T9–T11), usa a mesma sessão e não faz COMMIT.

Regras principais:

* Um pagamento por pedido (chave única ``pedido_id``, M05). Pedir de novo
  devolve o mesmo pagamento (200). Se o gateway caiu na primeira tentativa,
  o pagamento PENDENTE sem transação é reaproveitado, e o gateway devolve a
  mesma transação para a mesma referência (D39, ERR-003).
* Webhook idempotente (D43): o evento é gravado primeiro; a chave única
  ``evento_gateway`` barra o repetido, que responde 200 ``REPETIDO``.
* Aprovação tardia (D24): se o pedido já expirou ou foi cancelado, ele não
  volta; o pagamento vai para ESTORNO_SOLICITADO.
* O estorno é pedido ao gateway só depois do COMMIT (D33): os ``transacao_id``
  ficam em ``self.estornos``, e o controller agenda a chamada em segundo plano.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import FormaPagamento, OrigemAcao, StatusPagamento, StatusPedido, TipoPagamento
from app.models.evento_pagamento import EventoPagamento
from app.models.pagamento import Pagamento as PagamentoModel
from app.models.pedido import Pedido as PedidoModel
from app.nucleo.cliente_gateway import ClienteGateway
from app.nucleo.erros import ErroDominio
from app.nucleo.seguranca import Credencial
from app.services.auditoria import AuditoriaService
from app.services.pedidos import PedidoService
from app.views import pagamentos as v

P = StatusPagamento
S = StatusPedido

# Tipo do evento → status que o gateway informa (D43)
STATUS_DO_EVENTO = {"payment.approved": "APROVADO", "payment.refused": "RECUSADO", "refund.completed": "ESTORNADO"}


def _agora_utc(relogio: Callable[[], datetime]) -> datetime:
    return relogio().astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def _dinheiro(valor: Decimal) -> str:
    return f"{valor:.2f}"


def _view(p: PagamentoModel) -> v.Pagamento:
    return v.Pagamento(
        pagamento_id=p.id,
        pedido_id=p.pedido_id,
        tipo=p.tipo,
        forma=p.forma,
        valor=_dinheiro(p.valor),
        status=p.status,
        transacao_gateway=p.transacao_gateway,
        motivo_recusa=p.motivo_recusa,
    )


def _nao_aguarda_pagamento(pedido: PedidoModel, problema: str | None = None) -> ErroDominio:
    """409 da tabela 3.6.4 para as rotas 17 e 18 (D76, ERR-007)."""
    return ErroDominio(
        "PEDIDO_NAO_PAGAVEL",
        "O pedido não está aguardando pagamento",
        [{"campo": "status", "valor": S.PAGO.value, "problema": problema or f"status atual: {pedido.status.value}"}],
    )


class PagamentoService:
    def __init__(
        self, sessao: Session, relogio: Callable[[], datetime], cliente: ClienteGateway | None = None
    ) -> None:
        self.sessao = sessao
        self.relogio = relogio
        self.cliente = cliente
        self.estornos: list[str] = []  # transacao_id a estornar depois do COMMIT (D33)

    def _pedidos(self) -> PedidoService:
        return PedidoService(self.sessao, "", self.relogio)  # o JWT não é usado no T2 e no T3

    # ---- Pagamento online (RF13, UC06; D39) ----

    def solicitar_online(self, ator: Credencial, pedido_id: int, dados: v.PagamentoOnlineEntrada) -> tuple[v.Pagamento, bool]:
        """Devolve (pagamento, criado). ``criado`` False = pagamento que já existia (200)."""
        pedidos = self._pedidos()
        pedido = pedidos.obter_do_dono(ator, pedido_id)
        pagamento = self._do_pedido(pedido.id)

        if pagamento is not None and pagamento.tipo == TipoPagamento.BALCAO:
            raise _nao_aguarda_pagamento(pedido, "pedido pago no balcão")
        if pagamento is not None and pagamento.transacao_gateway is not None:
            return _view(pagamento), False  # mesma solicitação, mesma resposta (idempotente)

        if pedido.status != S.AGUARDANDO_PAGAMENTO:
            raise _nao_aguarda_pagamento(pedido)
        if pedidos.prazo_vencido(pedido):
            raise _nao_aguarda_pagamento(pedido, "prazo de pagamento de 15 minutos vencido (RN10)")

        if pagamento is None:
            pagamento = PagamentoModel(
                pedido_id=pedido.id,
                tipo=TipoPagamento.ONLINE,
                forma=FormaPagamento(dados.forma),
                valor=pedido.valor_total,  # o valor vem do pedido, nunca do corpo (OWASP API3)
                status=P.PENDENTE,
            )
            try:
                self.sessao.add(pagamento)
                self.sessao.commit()  # ERR-003: o PENDENTE fica gravado mesmo se o gateway cair
            except IntegrityError:  # outra requisição criou o pagamento ao mesmo tempo
                self.sessao.rollback()
                return _view(self._do_pedido(pedido.id)), False

        if self.cliente is None:
            raise ErroDominio("GATEWAY_INDISPONIVEL", "Gateway de pagamento indisponível; tente de novo")
        # 503 aqui: o pagamento fica PENDENTE sem transação, e a próxima tentativa o reaproveita
        transacao = self.cliente.criar_cobranca(str(pedido.id), _dinheiro(pagamento.valor), pagamento.forma.value)
        self.sessao.execute(
            update(PagamentoModel)
            .where(PagamentoModel.id == pagamento.id, PagamentoModel.transacao_gateway.is_(None))
            .values(transacao_gateway=transacao)
            .execution_options(synchronize_session=False)
        )
        self.sessao.commit()
        self.sessao.refresh(pagamento)
        return _view(pagamento), True

    # ---- Pagamento no balcão (RF14, UC09; D14) ----

    def confirmar_balcao(
        self, ator: Credencial, pedido_id: int, dados: v.PagamentoBalcaoEntrada, ip: str | None = None
    ) -> v.Pagamento:
        """ATENDENTE da unidade do pedido; não passa pelo gateway; o pedido vai direto para PAGO (T2)."""
        pedidos = self._pedidos()
        pedido = pedidos.obter(pedido_id)
        if ator.unidade_id != pedido.unidade_id:
            raise ErroDominio("SEM_PERMISSAO", "Unidade diferente da do token")
        if pedido.status != S.AGUARDANDO_PAGAMENTO:
            raise _nao_aguarda_pagamento(pedido)
        if pedidos.prazo_vencido(pedido):
            raise _nao_aguarda_pagamento(pedido, "prazo de pagamento de 15 minutos vencido (RN10)")
        if self._do_pedido(pedido.id) is not None:
            raise _nao_aguarda_pagamento(pedido, "pagamento online já solicitado")

        pagamento = PagamentoModel(
            pedido_id=pedido.id,
            tipo=TipoPagamento.BALCAO,
            forma=FormaPagamento(dados.forma),
            valor=pedido.valor_total,
            status=P.APROVADO,
        )
        try:
            self.sessao.add(pagamento)
            self.sessao.flush()
            if not pedidos.confirmar_pagamento(pedido, OrigemAcao.FUNCIONARIO):
                raise _nao_aguarda_pagamento(pedido)
            AuditoriaService(self.sessao).registrar(  # D14: pagamento fora do gateway fica na trilha
                "CONFIRMAR_PAGAMENTO_BALCAO",
                "pagamento",
                pagamento.id,
                ator=ator,
                unidade_id=pedido.unidade_id,
                detalhes={"pedido_id": pedido.id, "forma": pagamento.forma, "valor": pagamento.valor},
                ip=ip,
            )
            self.sessao.commit()
        except IntegrityError:  # outra requisição pagou o pedido ao mesmo tempo
            self.sessao.rollback()
            raise _nao_aguarda_pagamento(pedido, "pagamento já registrado") from None
        except Exception:
            self.sessao.rollback()
            raise
        self.sessao.refresh(pagamento)
        return _view(pagamento)

    # ---- Webhook (RF14, UC07; D24, D43) ----

    def processar_webhook(self, evento: v.EventoWebhook, payload: dict) -> v.ResultadoWebhook:
        """Assinatura já conferida no núcleo. Processa uma vez; o repetido responde REPETIDO."""
        if STATUS_DO_EVENTO[evento.tipo] != evento.status:
            raise ErroDominio(
                "VALIDACAO",
                "Dados de entrada inválidos",
                [{"campo": "status", "valor": evento.status, "problema": f"incompatível com o tipo {evento.tipo}"}],
            )
        pagamento = self.sessao.scalar(
            select(PagamentoModel).where(PagamentoModel.transacao_gateway == evento.transacao_id)
        )
        if pagamento is None or str(pagamento.pedido_id) != evento.referencia:
            raise ErroDominio("TRANSACAO_DESCONHECIDA", "Transação não encontrada")

        agora = _agora_utc(self.relogio)
        registro = EventoPagamento(
            evento_gateway=evento.evento_id, pagamento_id=pagamento.id, tipo=evento.tipo, payload=payload
        )
        try:
            self.sessao.add(registro)
            self.sessao.flush()  # a chave única barra o evento repetido (D43)
        except IntegrityError:
            self.sessao.rollback()
            return v.ResultadoWebhook(resultado="REPETIDO")

        try:
            if evento.tipo == "payment.approved":
                self._aprovado(pagamento)
            elif evento.tipo == "payment.refused":
                self._recusado(pagamento, evento.motivo)
            else:  # refund.completed
                self._mudar(pagamento, P.ESTORNO_SOLICITADO, P.ESTORNADO)
            registro.processado_em = agora
            self.sessao.commit()
        except Exception:
            self.sessao.rollback()
            self.estornos.clear()
            raise
        return v.ResultadoWebhook(resultado="PROCESSADO")

    def _aprovado(self, pagamento: PagamentoModel) -> None:
        if not self._mudar(pagamento, P.PENDENTE, P.APROVADO):
            return  # pagamento já decidido: o evento fica registrado, sem efeito
        pedidos = self._pedidos()
        pedido = pedidos.obter(pagamento.pedido_id)
        if not pedidos.confirmar_pagamento(pedido, OrigemAcao.GATEWAY):
            # D24: o pedido expirou ou foi cancelado antes da aprovação; não volta, e o dinheiro é devolvido
            self._mudar(pagamento, P.APROVADO, P.ESTORNO_SOLICITADO)
            self.estornos.append(pagamento.transacao_gateway)
            AuditoriaService(self.sessao).registrar(
                "ESTORNO_AUTOMATICO",
                "pagamento",
                pagamento.id,
                origem=OrigemAcao.GATEWAY,
                unidade_id=pedido.unidade_id,
                detalhes={"pedido_id": pedido.id, "status_pedido": pedido.status, "valor": pagamento.valor},
            )

    def _recusado(self, pagamento: PagamentoModel, motivo: str | None) -> None:
        if not self._mudar(pagamento, P.PENDENTE, P.RECUSADO, motivo_recusa=motivo):
            return
        pedidos = self._pedidos()
        pedidos.recusar_pagamento(pedidos.obter(pagamento.pedido_id), motivo)  # T3; se já expirou, nada muda

    # ---- Estorno (UC13; D24, D69) ----

    def solicitar_estorno(self, pedido_id: int) -> str | None:
        """Chamado pelo PedidoService no cancelamento (T9–T11), sem COMMIT.

        Online aprovado: ESTORNO_SOLICITADO, e devolve o ``transacao_id`` para o
        pedido ao gateway depois do COMMIT. Balcão: o dinheiro é devolvido no
        caixa, e o pagamento vai direto para ESTORNADO. Sem pagamento, nada muda.
        """
        pagamento = self._do_pedido(pedido_id)
        if pagamento is None or pagamento.status != P.APROVADO:
            return None
        if pagamento.tipo == TipoPagamento.BALCAO:
            self._mudar(pagamento, P.APROVADO, P.ESTORNADO)
            return None
        self._mudar(pagamento, P.APROVADO, P.ESTORNO_SOLICITADO)
        return pagamento.transacao_gateway

    # ---- Leitura (consulta do pedido, RF10) ----

    def obter_view(self, pedido_id: int) -> v.Pagamento | None:
        pagamento = self._do_pedido(pedido_id)
        return _view(pagamento) if pagamento is not None else None

    # ---- Apoio ----

    def _do_pedido(self, pedido_id: int) -> PagamentoModel | None:
        return self.sessao.scalar(select(PagamentoModel).where(PagamentoModel.pedido_id == pedido_id))

    def _mudar(self, pagamento: PagamentoModel, de: StatusPagamento, para: StatusPagamento, **valores) -> bool:
        """UPDATE condicional (D27): só muda se o status atual ainda for ``de``."""
        resultado = self.sessao.execute(
            update(PagamentoModel)
            .where(PagamentoModel.id == pagamento.id, PagamentoModel.status == de)
            .values(status=para, **valores)
            .execution_options(synchronize_session=False)
        )
        if resultado.rowcount != 1:
            return False
        self.sessao.flush()
        self.sessao.refresh(pagamento)
        return True
