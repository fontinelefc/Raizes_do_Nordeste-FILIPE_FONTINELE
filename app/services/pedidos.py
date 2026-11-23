"""PedidoService: pedidos multicanal e máquina de estados (RF09–RF12; RN05–RN08, RN10; D07, D31).

Dono das tabelas ``pedido``, ``item_pedido`` e ``historico_status_pedido``.
Lê unidade e cardápio pelo UnidadeService e mexe no saldo só pelo
EstoqueService (D52-7). É o service chamado pelo controller: faz o COMMIT, ou
o ROLLBACK quando uma regra falha (D52-5).

Máquina de estados (seção 3.4.1): toda mudança de status é um ``UPDATE``
condicional que só vale se o status atual for o de origem esperado (D27), com
uma linha em ``historico_status_pedido`` (M04). Se o UPDATE não afetar a linha,
a resposta é 409 TRANSICAO_INVALIDA e nada muda.

Autorização (3.6.5): o perfil e a unidade são checados aqui, porque dependem do
pedido; pedido de outro cliente responde 404, como se não existisse (OWASP API1).

Pagamento (E13): o T2 (PAGO, com baixa do estoque), o T3 (PAGAMENTO_RECUSADO,
com a reserva liberada) e a leitura do pedido para pagar são chamados pelo
PagamentoService, na sessão dele e sem COMMIT aqui (D52-5). O T4 (EXPIRADO) é
feito por ``expirar_vencidos``, chamado pela tarefa periódica (D71). No
cancelamento de pedido pago (T9–T11), o estorno é pedido ao PagamentoService, e
os ``transacao_id`` a estornar ficam em ``self.estornos``, para o controller
chamar o gateway só depois do COMMIT (D33, D69).

Pontos e auditoria (E14, D69): o T2 credita os pontos do cliente com
consentimento (RN14) e o cancelamento de pedido pago (T9–T11) os estorna, pelo
FidelidadeService; todo cancelamento grava auditoria (RN13), pelo
AuditoriaService, na mesma transação (ADR-07).
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import Canal, OrigemAcao, Perfil, StatusPedido
from app.models.historico_status_pedido import HistoricoStatusPedido
from app.models.item_pedido import ItemPedido as ItemPedidoModel
from app.models.pedido import Pedido as PedidoModel
from app.nucleo.erros import ErroDominio
from app.nucleo.seguranca import VALIDADE_TOKEN_PEDIDO, Credencial, gerar_token
from app.services.auditoria import AuditoriaService
from app.services.estoque import EstoqueService
from app.services.fidelidade import FidelidadeService
from app.services.unidades import UnidadeService
from app.views import pedidos as v

S = StatusPedido
EXPIRACAO = timedelta(minutes=15)  # RN10, D08
LOTE_EXPIRACAO = 100  # pedidos vencidos tratados por rodada da tarefa (D71)

# Canais por quem cria o pedido (endpoint 12)
CANAIS_ANONIMO = {Canal.APP, Canal.TOTEM, Canal.PICKUP}
CANAIS_CLIENTE = {Canal.APP, Canal.PICKUP}

# T6–T8: status pedido → (status de origem, perfil que pode pedir)
AVANCOS = {
    S.EM_PREPARO: (S.PAGO, Perfil.COZINHA),
    S.PRONTO: (S.EM_PREPARO, Perfil.COZINHA),
    S.ENTREGUE: (S.PRONTO, Perfil.ATENDENTE),
}

# T5, T9: o dono cancela antes do preparo; T5, T9–T11: o GERENTE da unidade
CANCELAVEIS_DONO = {S.AGUARDANDO_PAGAMENTO, S.PAGO}
CANCELAVEIS_GERENTE = {S.AGUARDANDO_PAGAMENTO, S.PAGO, S.EM_PREPARO, S.PRONTO}


def _utc_sem_fuso(momento: datetime) -> datetime:
    # O banco grava DATETIME em UTC sem fuso (M12, D55)
    return momento.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def _dinheiro(valor: Decimal) -> str:
    return f"{valor:.2f}"


def _nao_encontrado() -> ErroDominio:
    return ErroDominio("NAO_ENCONTRADO", "Pedido não encontrado")


def _sem_permissao(mensagem: str) -> ErroDominio:
    return ErroDominio("SEM_PERMISSAO", mensagem)


def _transicao_invalida(atual: StatusPedido, pedido: StatusPedido) -> ErroDominio:
    return ErroDominio(
        "TRANSICAO_INVALIDA",
        "Mudança de status não permitida",
        [{"campo": "status", "valor": pedido.value, "problema": f"status atual: {atual.value}"}],
    )


def _view_pedido(p: PedidoModel, token_pedido: str | None = None) -> v.Pedido:
    return v.Pedido(
        id=p.id,
        unidade_id=p.unidade_id,
        cliente_id=p.cliente_id,
        canal=p.canal,
        status=p.status,
        valor_total=_dinheiro(p.valor_total),
        expira_em=p.expira_em,
        criado_em=p.criado_em,
        itens=[
            v.ItemPedido(
                produto_id=i.produto_id,
                nome=i.produto.nome,
                quantidade=i.quantidade,
                preco_unitario=_dinheiro(i.preco_unitario),
                subtotal=_dinheiro(i.subtotal),
            )
            for i in p.itens
        ],
        token_pedido=token_pedido,
    )


class PedidoService:
    def __init__(self, sessao: Session, jwt_segredo: str, relogio: Callable[[], datetime]) -> None:
        self.sessao = sessao
        self.jwt_segredo = jwt_segredo
        self.relogio = relogio  # D70: trocado nos testes para fixar a hora
        self.estornos: list[str] = []  # transacao_id a estornar depois do COMMIT (D33)

    # ---- Criar (T1; RF09, RF15; RN05, RN06, RN10) ----

    def criar(self, ator: Credencial | None, dados: v.PedidoEntrada) -> v.Pedido:
        cliente_id, origem = self._autorizar_criacao(ator, dados)
        unidades = UnidadeService(self.sessao)
        agora = self.relogio()

        unidade = unidades.obter_unidade(dados.unidade_id)
        if unidade is None:
            raise ErroDominio("NAO_ENCONTRADO", "Unidade não encontrada")
        if not unidades.esta_aberta(unidade, agora):
            raise ErroDominio("UNIDADE_FECHADA", "Unidade inativa ou fora do horário de funcionamento")

        produto_ids = [item.produto_id for item in dados.itens]
        repetidos = [i for i, pid in enumerate(produto_ids) if pid in produto_ids[:i]]
        if repetidos:
            i = repetidos[0]
            raise ErroDominio(
                "VALIDACAO",
                "Dados de entrada inválidos",
                [{"campo": f"itens[{i}].produto_id", "valor": produto_ids[i], "problema": "produto repetido no pedido"}],
            )

        vendaveis = unidades.itens_vendaveis(unidade, produto_ids)
        faltando = [i for i, pid in enumerate(produto_ids) if pid not in vendaveis]
        if faltando:
            raise ErroDominio(
                "ITEM_INDISPONIVEL",
                "Produto fora do cardápio da unidade ou indisponível",
                [
                    {"campo": f"itens[{i}].produto_id", "valor": produto_ids[i], "problema": "indisponível na unidade"}
                    for i in faltando
                ],
            )

        criado_em = _utc_sem_fuso(agora)
        itens = [
            ItemPedidoModel(
                produto_id=item.produto_id,
                produto=vendaveis[item.produto_id].produto,
                quantidade=item.quantidade,
                preco_unitario=vendaveis[item.produto_id].preco,  # M08: o preço vem do cardápio
                subtotal=vendaveis[item.produto_id].preco * item.quantidade,
            )
            for item in dados.itens
        ]
        pedido = PedidoModel(
            unidade_id=unidade.id,
            cliente_id=cliente_id,
            canal=dados.canal,
            status=S.AGUARDANDO_PAGAMENTO,
            valor_total=sum((i.subtotal for i in itens), Decimal("0.00")),
            expira_em=criado_em + EXPIRACAO,
            criado_em=criado_em,
            itens=itens,
        )
        try:
            EstoqueService(self.sessao).reservar(
                unidade.id,
                [(f"itens[{i}].produto_id", item.produto_id, item.quantidade) for i, item in enumerate(dados.itens)],
            )
            self.sessao.add(pedido)
            self.sessao.flush()  # gera o id do pedido
            self._registrar(pedido.id, None, S.AGUARDANDO_PAGAMENTO, origem, None, criado_em)
            self.sessao.commit()
        except (ErroDominio, IntegrityError):
            self.sessao.rollback()  # ESTOQUE_INSUFICIENTE: nenhum item fica reservado
            raise

        token = None
        if ator is None:  # D46: o anônimo recebe um token que só vale para este pedido
            token, _ = gerar_token(Credencial("PEDIDO", pedido.id), self.jwt_segredo, VALIDADE_TOKEN_PEDIDO)
        return _view_pedido(pedido, token)

    @staticmethod
    def _autorizar_criacao(ator: Credencial | None, dados: v.PedidoEntrada) -> tuple[int | None, OrigemAcao]:
        if ator is None:
            if dados.canal not in CANAIS_ANONIMO:  # o balcão exige o login do atendente
                raise ErroDominio("NAO_AUTENTICADO", "O canal BALCAO exige o login do atendente")
            return None, OrigemAcao.CLIENTE
        if ator.tipo == "CLIENTE":
            if dados.canal not in CANAIS_CLIENTE:
                raise _sem_permissao("O cliente só cria pedidos pelos canais APP e PICKUP")
            return ator.id, OrigemAcao.CLIENTE
        if ator.tipo == "FUNCIONARIO" and ator.perfil == Perfil.ATENDENTE:
            if dados.canal != Canal.BALCAO:
                raise _sem_permissao("O atendente só cria pedidos pelo canal BALCAO")
            if ator.unidade_id != dados.unidade_id:
                raise _sem_permissao("Unidade diferente da do token")
            return None, OrigemAcao.FUNCIONARIO
        raise _sem_permissao("Perfil sem acesso a esta operação")

    # ---- Consultar (RF10) e painel (RF10, RF11) ----

    def consultar(self, ator: Credencial, pedido_id: int) -> v.PedidoDetalhe:
        pedido = self._pedido_visivel(ator, pedido_id)
        return v.PedidoDetalhe(
            **_view_pedido(pedido).model_dump(exclude={"token_pedido"}),
            historico=[
                v.HistoricoStatus(status=h.status_novo, origem=h.origem, em=h.criado_em) for h in pedido.historico
            ],
            pagamento=self._pagamentos().obter_view(pedido.id),
        )

    def painel(
        self, ator: Credencial, unidade_id: int, status: StatusPedido | None, limit: int, offset: int
    ) -> v.ListaPedidos:
        """Funcionário da unidade ou MATRIZ; mais antigos primeiro (fila da cozinha, UC11)."""
        if ator.tipo != "FUNCIONARIO":
            raise _sem_permissao("Perfil sem acesso a esta operação")
        if ator.perfil != Perfil.MATRIZ and ator.unidade_id != unidade_id:
            raise _sem_permissao("Unidade diferente da do token")
        if UnidadeService(self.sessao).obter_unidade(unidade_id) is None:
            raise ErroDominio("NAO_ENCONTRADO", "Unidade não encontrada")
        filtros = [PedidoModel.unidade_id == unidade_id]
        if status is not None:
            filtros.append(PedidoModel.status == status)
        total = self.sessao.scalar(select(func.count()).select_from(PedidoModel).where(*filtros))
        pedidos = self.sessao.scalars(
            select(PedidoModel)
            .where(*filtros)
            .order_by(PedidoModel.criado_em, PedidoModel.id)
            .limit(limit)
            .offset(offset)
        )
        return v.ListaPedidos(itens=[_view_pedido(p) for p in pedidos], total=total)

    # ---- Avançar status (T6–T8; RF11) ----

    def avancar(self, ator: Credencial, pedido_id: int, dados: v.StatusPedidoEntrada) -> v.Pedido:
        destino = S(dados.status)
        origem_esperada, perfil = AVANCOS[destino]
        if ator.tipo != "FUNCIONARIO" or ator.perfil != perfil:
            raise _sem_permissao(f"Só o perfil {perfil.value} leva o pedido para {destino.value}")
        pedido = self._obter(pedido_id)
        if ator.unidade_id != pedido.unidade_id:
            raise _sem_permissao("Unidade diferente da do token")
        self._transicionar(pedido, origem_esperada, destino, OrigemAcao.FUNCIONARIO, None)
        self.sessao.commit()
        return _view_pedido(pedido)

    # ---- Cancelar (T5, T9–T11; RF12; RN08; D25) ----

    def cancelar(
        self, ator: Credencial, pedido_id: int, dados: v.CancelamentoEntrada, ip: str | None = None
    ) -> v.Pedido:
        justificativa = dados.justificativa.strip()
        if len(justificativa) < 10:  # o corpo já barra menos de 10; aqui barra os espaços em branco
            raise ErroDominio(
                "JUSTIFICATIVA_OBRIGATORIA",
                "A justificativa precisa ter pelo menos 10 caracteres",
                [{"campo": "justificativa", "valor": dados.justificativa, "problema": "mínimo de 10 caracteres"}],
            )

        if ator.tipo == "FUNCIONARIO":
            if ator.perfil != Perfil.GERENTE:
                raise _sem_permissao("Só o GERENTE da unidade cancela pedidos")
            pedido = self._obter(pedido_id)
            if ator.unidade_id != pedido.unidade_id:
                raise _sem_permissao("Unidade diferente da do token")
            permitidos, origem = CANCELAVEIS_GERENTE, OrigemAcao.FUNCIONARIO
        else:
            pedido = self._pedido_visivel(ator, pedido_id)
            permitidos, origem = CANCELAVEIS_DONO, OrigemAcao.CLIENTE

        anterior = pedido.status
        if anterior not in permitidos:
            raise _transicao_invalida(anterior, S.CANCELADO)
        try:
            self._transicionar(pedido, anterior, S.CANCELADO, origem, justificativa)
            itens = [(i.produto_id, i.quantidade) for i in pedido.itens]
            estoque = EstoqueService(self.sessao)
            if anterior == S.AGUARDANDO_PAGAMENTO:  # T5: a reserva volta ao disponível
                estoque.liberar(pedido.unidade_id, itens)
            elif anterior == S.PAGO:  # T9: a baixa volta ao saldo (D25)
                estoque.devolver(pedido.unidade_id, itens)
            # T10, T11: o preparo começou; o estoque não volta, é perda (D25)
            pontos = 0
            if anterior != S.AGUARDANDO_PAGAMENTO:  # T9–T11: o dinheiro e os pontos voltam (D69, RN14)
                transacao = self._pagamentos().solicitar_estorno(pedido.id)
                if transacao is not None:
                    self.estornos.append(transacao)
                if pedido.cliente_id is not None:
                    pontos = FidelidadeService(self.sessao).estornar_pontos(pedido.cliente_id, pedido.id)
            AuditoriaService(self.sessao).registrar(
                "CANCELAR_PEDIDO",
                "pedido",
                pedido.id,
                ator=ator,
                unidade_id=pedido.unidade_id,
                detalhes={
                    "antes": {"status": anterior},
                    "depois": {"status": S.CANCELADO},
                    "justificativa": justificativa,
                    "pontos_estornados": pontos,
                },
                ip=ip,
            )
            self.sessao.commit()
        except (ErroDominio, IntegrityError):
            self.sessao.rollback()
            raise
        return _view_pedido(pedido)

    # ---- Pagamento (T2, T3; chamados pelo PagamentoService, sem COMMIT) ----

    def obter(self, pedido_id: int) -> PedidoModel:
        return self._obter(pedido_id)

    def obter_do_dono(self, ator: Credencial, pedido_id: int) -> PedidoModel:
        """Pagamento online: só o dono (cliente ou token_pedido); o resto recebe 404 (OWASP API1)."""
        if ator.tipo not in {"CLIENTE", "PEDIDO"}:
            raise _nao_encontrado()
        return self._pedido_visivel(ator, pedido_id)

    def prazo_vencido(self, pedido: PedidoModel) -> bool:
        """RN10: passou dos 15 min, mesmo que a tarefa de expiração ainda não tenha rodado."""
        return pedido.expira_em is not None and _utc_sem_fuso(self.relogio()) >= pedido.expira_em

    def confirmar_pagamento(self, pedido: PedidoModel, origem: OrigemAcao) -> bool:
        """T2: AGUARDANDO_PAGAMENTO → PAGO, baixa do estoque e pontos (RN14). False se o pedido já saiu desse status."""
        if not self._mudar_status(pedido, S.AGUARDANDO_PAGAMENTO, S.PAGO, origem, None):
            return False
        EstoqueService(self.sessao).baixar(pedido.unidade_id, [(i.produto_id, i.quantidade) for i in pedido.itens])
        if pedido.cliente_id is not None:  # RN14: só depois do pagamento confirmado, com consentimento
            FidelidadeService(self.sessao).creditar_pontos(pedido.cliente_id, pedido.id, pedido.valor_total)
        return True

    def recusar_pagamento(self, pedido: PedidoModel, motivo: str | None) -> bool:
        """T3: AGUARDANDO_PAGAMENTO → PAGAMENTO_RECUSADO e a reserva volta ao disponível."""
        if not self._mudar_status(pedido, S.AGUARDANDO_PAGAMENTO, S.PAGAMENTO_RECUSADO, OrigemAcao.GATEWAY, motivo):
            return False
        EstoqueService(self.sessao).liberar(pedido.unidade_id, [(i.produto_id, i.quantidade) for i in pedido.itens])
        return True

    # ---- Expiração (T4; RN10; UC14; D71) ----

    def expirar_vencidos(self) -> int:
        """Expira os pedidos com o prazo vencido e libera a reserva; um COMMIT por pedido.

        Chamado pela tarefa periódica (D71), que faz o papel do controller. Se o
        webhook aprovar o pedido ao mesmo tempo, o UPDATE condicional deixa passar
        só um dos dois (D27); o perdedor é ignorado aqui, e a aprovação tardia vira
        estorno no PagamentoService (D24).
        """
        agora = _utc_sem_fuso(self.relogio())
        vencidos = self.sessao.scalars(
            select(PedidoModel.id)
            .where(PedidoModel.status == S.AGUARDANDO_PAGAMENTO, PedidoModel.expira_em <= agora)
            .order_by(PedidoModel.expira_em, PedidoModel.id)
            .limit(LOTE_EXPIRACAO)
        ).all()
        expirados = 0
        for pedido_id in vencidos:
            pedido = self._obter(pedido_id)
            try:
                if self._mudar_status(pedido, S.AGUARDANDO_PAGAMENTO, S.EXPIRADO, OrigemAcao.SISTEMA, None):
                    EstoqueService(self.sessao).liberar(
                        pedido.unidade_id, [(i.produto_id, i.quantidade) for i in pedido.itens]
                    )
                    expirados += 1
                self.sessao.commit()
            except Exception:
                self.sessao.rollback()
                raise
        return expirados

    # ---- Apoio ----

    def _pagamentos(self):
        from app.services.pagamentos import PagamentoService  # importado aqui: os dois services se chamam

        return PagamentoService(self.sessao, self.relogio)

    def _obter(self, pedido_id: int) -> PedidoModel:
        pedido = self.sessao.get(PedidoModel, pedido_id)
        if pedido is None:
            raise _nao_encontrado()
        return pedido

    def _pedido_visivel(self, ator: Credencial, pedido_id: int) -> PedidoModel:
        """Nível 3 (objeto): quem não pode ver o pedido recebe 404, como se ele não existisse."""
        pedido = self._obter(pedido_id)
        if ator.tipo == "CLIENTE":
            visivel = pedido.cliente_id == ator.id
        elif ator.tipo == "PEDIDO":  # token_pedido vale só para o próprio pedido (D46)
            visivel = pedido.id == ator.id
        else:  # funcionário: a própria unidade; a MATRIZ vê todas (RN12)
            visivel = ator.perfil == Perfil.MATRIZ or pedido.unidade_id == ator.unidade_id
        if not visivel:
            raise _nao_encontrado()
        return pedido

    def _transicionar(
        self, pedido: PedidoModel, de: StatusPedido, para: StatusPedido, origem: OrigemAcao, motivo: str | None
    ) -> None:
        """Como ``_mudar_status``, mas desfaz a transação e responde 409 se o status mudou antes."""
        if not self._mudar_status(pedido, de, para, origem, motivo):
            self.sessao.rollback()
            atual = self.sessao.scalar(select(PedidoModel.status).where(PedidoModel.id == pedido.id))
            raise _transicao_invalida(atual, para)

    def _mudar_status(
        self, pedido: PedidoModel, de: StatusPedido, para: StatusPedido, origem: OrigemAcao, motivo: str | None
    ) -> bool:
        """UPDATE condicional (D27): só muda se o status atual ainda for ``de``; grava o histórico."""
        valores = {"status": para}
        if de == S.AGUARDANDO_PAGAMENTO:
            valores["expira_em"] = None  # só o pedido aguardando pagamento expira (T4)
        resultado = self.sessao.execute(
            update(PedidoModel)
            .where(PedidoModel.id == pedido.id, PedidoModel.status == de)
            .values(**valores)
            .execution_options(synchronize_session=False)
        )
        if resultado.rowcount != 1:
            return False
        self._registrar(pedido.id, de, para, origem, motivo, _utc_sem_fuso(self.relogio()))
        self.sessao.flush()
        self.sessao.refresh(pedido)
        return True

    def _registrar(
        self,
        pedido_id: int,
        de: StatusPedido | None,
        para: StatusPedido,
        origem: OrigemAcao,
        motivo: str | None,
        em: datetime,
    ) -> None:
        self.sessao.add(
            HistoricoStatusPedido(
                pedido_id=pedido_id, status_anterior=de, status_novo=para, origem=origem, motivo=motivo, criado_em=em
            )
        )
