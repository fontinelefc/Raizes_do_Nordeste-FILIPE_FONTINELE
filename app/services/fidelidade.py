"""FidelidadeService: dono das tabelas ``cliente``, ``consentimento`` e ``movimentacao_pontos`` (D52).

Faz três coisas:

* Cliente (E11): grava e busca o cliente para o cadastro e o login do domínio
  Acesso (D52-7).
* LGPD (E14; RF20, RF25; RN16–RN18): dados do titular e consentimentos por
  finalidade. Cada aceite é uma nova linha (M09); revogar preenche
  ``revogado_em`` e preserva o histórico. Toda leitura e escrita de dados
  pessoais grava auditoria (3.6.5).
* Pontos (E14; RF17; RN14; D74): o crédito no T2 e o estorno no cancelamento
  (T9–T11) são chamados pelo PedidoService, na mesma sessão.

Regra de transação (D52-5): os métodos das rotas 20–24 são chamados pelo
controller e fazem o COMMIT; ``criar_cliente``, ``creditar_pontos`` e
``estornar_pontos`` são chamados por outro service e não fazem COMMIT.

As datas de ``consentimento`` e ``movimentacao_pontos`` vêm do relógio do banco
(``CURRENT_TIMESTAMP``, em UTC pela sessão, D55-5), para a restrição
``revogado_em >= concedido_em`` valer sempre.
"""

from decimal import ROUND_DOWN, Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.cliente import Cliente
from app.models.consentimento import Consentimento as ConsentimentoModel
from app.models.enums import FaixaEtaria, Finalidade, TipoMovPontos
from app.models.movimentacao_pontos import MovimentacaoPontos as MovimentacaoModel
from app.nucleo.erros import ErroDominio
from app.nucleo.seguranca import Credencial
from app.services.auditoria import AuditoriaService
from app.views import acesso as va
from app.views import fidelidade as v


def _email_ja_cadastrado() -> ErroDominio:
    return ErroDominio("EMAIL_JA_CADASTRADO", "Já existe um cliente com este e-mail")


def _vigente(cliente_id: int, finalidade: Finalidade):
    return select(ConsentimentoModel).where(
        ConsentimentoModel.cliente_id == cliente_id,
        ConsentimentoModel.finalidade == finalidade,
        ConsentimentoModel.revogado_em.is_(None),
    )


def pontos_do_valor(valor: Decimal) -> int:
    """RN14, D74: 1 ponto por R$ 1,00, sem os centavos (R$ 37,90 → 37)."""
    return int(valor.quantize(Decimal("1"), rounding=ROUND_DOWN))


class FidelidadeService:
    def __init__(self, sessao: Session) -> None:
        self.sessao = sessao

    # ---- Cliente (usado pelo AcessoService, E11) ----

    def buscar_cliente_por_email(self, email: str) -> Cliente | None:
        return self.sessao.scalar(select(Cliente).where(Cliente.email == email))

    def criar_cliente(
        self,
        nome: str,
        email: str,
        telefone: str | None,
        senha_hash: str,
        faixa_etaria: FaixaEtaria | None,
    ) -> Cliente:
        if self.buscar_cliente_por_email(email) is not None:
            raise _email_ja_cadastrado()
        cliente = Cliente(
            nome=nome, email=email, telefone=telefone, senha_hash=senha_hash, faixa_etaria=faixa_etaria
        )
        self.sessao.add(cliente)
        try:
            self.sessao.flush()  # gera o id; a chave única barra o cadastro simultâneo
        except IntegrityError:
            raise _email_ja_cadastrado() from None
        self.sessao.refresh(cliente)  # traz saldo_pontos e criado_em gerados pelo banco
        return cliente

    # ---- Dados do titular e extrato (endpoints 20 e 21; RF17, RF25) ----

    def dados_cliente(self, ator: Credencial, ip: str | None = None) -> va.Cliente:
        cliente = self._cliente(ator)
        self._auditar(ator, "LER_DADOS_CLIENTE", "cliente", cliente.id, ip=ip)
        self.sessao.commit()
        return va.Cliente.model_validate(cliente, from_attributes=True)

    def extrato(self, ator: Credencial, limit: int, offset: int) -> v.ListaMovimentacoes:
        """Mais recentes primeiro; o saldo fica em ``GET /clientes/me``."""
        filtro = MovimentacaoModel.cliente_id == ator.id
        total = self.sessao.scalar(select(func.count()).select_from(MovimentacaoModel).where(filtro))
        movimentos = self.sessao.scalars(
            select(MovimentacaoModel)
            .where(filtro)
            .order_by(MovimentacaoModel.criado_em.desc(), MovimentacaoModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return v.ListaMovimentacoes(
            itens=[v.MovimentacaoPontos.model_validate(m, from_attributes=True) for m in movimentos], total=total
        )

    # ---- Consentimentos (endpoints 22–24; RF20, UC21; RN16, RN17) ----

    def listar_consentimentos(self, ator: Credencial, ip: str | None = None) -> list[v.Consentimento]:
        """Vigentes e revogados, do mais antigo ao mais novo (histórico, M09)."""
        consentimentos = self.sessao.scalars(
            select(ConsentimentoModel)
            .where(ConsentimentoModel.cliente_id == ator.id)
            .order_by(ConsentimentoModel.id)
        ).all()
        self._auditar(ator, "LER_CONSENTIMENTOS", "cliente", ator.id, ip=ip)
        self.sessao.commit()
        return [v.Consentimento.model_validate(c, from_attributes=True) for c in consentimentos]

    def conceder_consentimento(
        self, ator: Credencial, dados: v.ConsentimentoEntrada, ip: str | None = None
    ) -> v.Consentimento:
        try:
            # Trava a linha do cliente: dois aceites simultâneos não geram dois vigentes
            cliente = self.sessao.scalar(select(Cliente).where(Cliente.id == ator.id).with_for_update())
            if cliente is None:
                raise _nao_autenticado()
            if cliente.faixa_etaria == FaixaEtaria.MENOR_18 and not dados.autorizado_responsavel:  # RN17
                raise ErroDominio(
                    "AUTORIZACAO_RESPONSAVEL_OBRIGATORIA",
                    "Cliente menor de 18 anos precisa da autorização do responsável",
                    [{"campo": "autorizado_responsavel", "valor": False, "problema": "obrigatório para MENOR_18"}],
                )
            finalidade = Finalidade(dados.finalidade)
            if self.sessao.scalar(_vigente(cliente.id, finalidade)) is not None:
                raise ErroDominio("CONSENTIMENTO_VIGENTE", "Já existe consentimento vigente para a finalidade")
            consentimento = ConsentimentoModel(
                cliente_id=cliente.id,
                finalidade=finalidade,
                versao_termo=dados.versao_termo,
                autorizado_responsavel=dados.autorizado_responsavel,
            )
            self.sessao.add(consentimento)
            self.sessao.flush()
            self._auditar(
                ator,
                "CONCEDER_CONSENTIMENTO",
                "consentimento",
                consentimento.id,
                {"finalidade": finalidade, "versao_termo": dados.versao_termo},
                ip,
            )
            self.sessao.commit()
        except Exception:
            self.sessao.rollback()
            raise
        self.sessao.refresh(consentimento)  # concedido_em vem do banco
        return v.Consentimento.model_validate(consentimento, from_attributes=True)

    def revogar_consentimento(self, ator: Credencial, finalidade: Finalidade, ip: str | None = None) -> None:
        """RN16: revogável a qualquer momento; sem consentimento vigente, 404."""
        try:
            consentimento = self.sessao.scalar(_vigente(ator.id, finalidade).with_for_update())
            if consentimento is None:
                raise ErroDominio("NAO_ENCONTRADO", "Não há consentimento vigente para a finalidade")
            self.sessao.execute(
                update(ConsentimentoModel)
                .where(ConsentimentoModel.id == consentimento.id, ConsentimentoModel.revogado_em.is_(None))
                .values(revogado_em=func.current_timestamp())
                .execution_options(synchronize_session=False)
            )
            self._auditar(
                ator,
                "REVOGAR_CONSENTIMENTO",
                "consentimento",
                consentimento.id,
                {"finalidade": finalidade, "versao_termo": consentimento.versao_termo},
                ip,
            )
            self.sessao.commit()
        except Exception:
            self.sessao.rollback()
            raise

    # ---- Pontos (RF17; RN14; D74; chamados pelo PedidoService, sem COMMIT) ----

    def creditar_pontos(self, cliente_id: int, pedido_id: int, valor: Decimal) -> int:
        """T2: credita se o cliente tem consentimento FIDELIDADE vigente (RN16). Devolve os pontos."""
        if self.sessao.scalar(_vigente(cliente_id, Finalidade.FIDELIDADE)) is None:
            return 0
        pontos = pontos_do_valor(valor)
        if pontos <= 0:  # pedido abaixo de R$ 1,00
            return 0
        self.sessao.add(
            MovimentacaoModel(cliente_id=cliente_id, pedido_id=pedido_id, tipo=TipoMovPontos.CREDITO, pontos=pontos)
        )
        self._somar_saldo(cliente_id, pontos)
        return pontos

    def estornar_pontos(self, cliente_id: int, pedido_id: int) -> int:
        """T9–T11: devolve o que o pedido creditou, mesmo que o consentimento já tenha sido revogado."""
        liquido = self.sessao.scalar(
            select(func.coalesce(func.sum(MovimentacaoModel.pontos), 0)).where(
                MovimentacaoModel.cliente_id == cliente_id, MovimentacaoModel.pedido_id == pedido_id
            )
        )
        if liquido <= 0:  # nada creditado, ou já estornado
            return 0
        saldo = self.sessao.scalar(select(Cliente.saldo_pontos).where(Cliente.id == cliente_id).with_for_update())
        pontos = min(int(liquido), saldo)  # o saldo nunca fica negativo (CHECK ck_cliente_saldo)
        if pontos <= 0:
            return 0
        self.sessao.add(
            MovimentacaoModel(cliente_id=cliente_id, pedido_id=pedido_id, tipo=TipoMovPontos.ESTORNO, pontos=-pontos)
        )
        self._somar_saldo(cliente_id, -pontos)
        return pontos

    # ---- Apoio ----

    def _cliente(self, ator: Credencial) -> Cliente:
        cliente = self.sessao.get(Cliente, ator.id)
        if cliente is None:  # token de um cliente que não existe mais na base
            raise _nao_autenticado()
        return cliente

    def _somar_saldo(self, cliente_id: int, pontos: int) -> None:
        self.sessao.execute(
            update(Cliente)
            .where(Cliente.id == cliente_id)
            .values(saldo_pontos=Cliente.saldo_pontos + pontos)
            .execution_options(synchronize_session=False)
        )
        self.sessao.flush()

    def _auditar(
        self,
        ator: Credencial,
        acao: str,
        entidade: str,
        entidade_id: int,
        detalhes: dict | None = None,
        ip: str | None = None,
    ) -> None:
        AuditoriaService(self.sessao).registrar(acao, entidade, entidade_id, ator=ator, detalhes=detalhes, ip=ip)


def _nao_autenticado() -> ErroDominio:
    return ErroDominio("NAO_AUTENTICADO", "Token inválido ou expirado")
