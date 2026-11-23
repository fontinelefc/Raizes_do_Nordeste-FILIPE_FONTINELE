"""UnidadeService: unidades, catálogo padrão e cardápio por unidade (RF03–RF05, RF08).

Dono das tabelas ``unidade``, ``produto`` e ``item_cardapio`` (D52). Aqui ficam
as regras que o banco não consegue checar sozinho, porque envolvem duas tabelas
(D55): o preço local dentro da faixa do produto (RN01) e o produto que exige
cozinha completa numa unidade REDUZIDA (RN02).

Autorização por unidade (nível 2 da 3.6.5): o GERENTE só mexe no cardápio da
própria unidade; a MATRIZ mexe em todas (RN12).

Auditoria (E14, D65): cadastro e alteração de unidade e de produto e a definição
de preço e disponibilidade no cardápio gravam um registro com o antes e o depois,
pelo AuditoriaService, na mesma transação (ADR-07).
"""

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import Perfil, TipoOperacao
from app.models.item_cardapio import ItemCardapio as ItemCardapioModel
from app.models.produto import Produto as ProdutoModel
from app.models.unidade import Unidade as UnidadeModel
from app.nucleo.erros import ErroDominio
from app.nucleo.seguranca import Credencial
from app.services.auditoria import AuditoriaService
from app.views import unidades as v

FORMATO_HORARIO = "%H:%M"
# D70: horário das unidades na hora local. Recife, Fortaleza e Salvador usam UTC−3 sem horário de verão
FUSO_UNIDADES = ZoneInfo("America/Recife")


# ---- Conversões entre o banco e as views ----

def _dinheiro(valor: Decimal) -> str:
    return f"{valor:.2f}"


def _horario_texto(valor: time) -> str:
    return valor.strftime(FORMATO_HORARIO)


def _horario(campo: str, valor: str) -> time:
    try:
        return datetime.strptime(valor, FORMATO_HORARIO).time()
    except ValueError:
        raise _validacao(campo, valor, "use o formato HH:MM, ex.: 06:00") from None


def _validacao(campo: str, valor, problema: str) -> ErroDominio:
    return ErroDominio("VALIDACAO", "Dados de entrada inválidos", [{"campo": campo, "valor": valor, "problema": problema}])


def _view_unidade(u: UnidadeModel) -> v.Unidade:
    return v.Unidade(
        id=u.id,
        nome=u.nome,
        tipo_operacao=u.tipo_operacao,
        cidade=u.cidade,
        uf=u.uf,
        horario_abertura=_horario_texto(u.horario_abertura),
        horario_fechamento=_horario_texto(u.horario_fechamento),
        ativa=u.ativa,
        criado_em=u.criado_em,
    )


def _view_produto(p: ProdutoModel) -> v.Produto:
    return v.Produto(
        id=p.id,
        codigo=p.codigo,
        nome=p.nome,
        descricao=p.descricao,
        categoria=p.categoria,
        preco_base=_dinheiro(p.preco_base),
        preco_minimo=_dinheiro(p.preco_minimo),
        preco_maximo=_dinheiro(p.preco_maximo),
        exige_cozinha_completa=p.exige_cozinha_completa,
        ativo=p.ativo,
    )


def _view_item(item: ItemCardapioModel) -> v.ItemCardapio:
    p = item.produto
    return v.ItemCardapio(
        produto_id=p.id,
        nome=p.nome,
        descricao=p.descricao,
        categoria=p.categoria,
        preco=_dinheiro(item.preco),
        disponivel=item.disponivel,
    )


def _mudancas(dados, anulaveis: set[str] = frozenset()) -> dict:
    """Campos enviados no PATCH. ``null`` só é aceito em coluna que aceita nulo."""
    mudancas = dados.model_dump(exclude_unset=True)
    for campo, valor in mudancas.items():
        if valor is None and campo not in anulaveis:
            raise _validacao(campo, None, "o campo não aceita null")
    return mudancas


def _conferir_faixa(minimo: Decimal, base: Decimal, maximo: Decimal) -> None:
    # RN01: 0 < preco_minimo <= preco_base <= preco_maximo (o CHECK do banco é a última barreira)
    if not (Decimal("0") < minimo <= base <= maximo):
        raise ErroDominio(
            "VALIDACAO",
            "Dados de entrada inválidos",
            [
                {
                    "campo": "preco_base",
                    "valor": _dinheiro(base),
                    "problema": "a faixa precisa respeitar 0 < preco_minimo <= preco_base <= preco_maximo",
                }
            ],
        )


def _nao_encontrado(recurso: str) -> ErroDominio:
    return ErroDominio("NAO_ENCONTRADO", f"{recurso} não encontrado(a)")


class UnidadeService:
    def __init__(self, sessao: Session) -> None:
        self.sessao = sessao

    # ---- Unidades (RF03) ----

    def listar_unidades(self, limit: int, offset: int) -> v.ListaUnidades:
        """Só unidades ativas: é a lista que os canais mostram ao cliente (UC01)."""
        filtro = UnidadeModel.ativa.is_(True)
        total = self.sessao.scalar(select(func.count()).select_from(UnidadeModel).where(filtro))
        unidades = self.sessao.scalars(
            select(UnidadeModel).where(filtro).order_by(UnidadeModel.id).limit(limit).offset(offset)
        )
        return v.ListaUnidades(itens=[_view_unidade(u) for u in unidades], total=total)

    def cadastrar_unidade(self, ator: Credencial, dados: v.UnidadeEntrada, ip: str | None = None) -> v.Unidade:
        unidade = UnidadeModel(
            nome=dados.nome,
            tipo_operacao=dados.tipo_operacao,
            cidade=dados.cidade,
            uf=dados.uf,
            horario_abertura=_horario("horario_abertura", dados.horario_abertura),
            horario_fechamento=_horario("horario_fechamento", dados.horario_fechamento),
        )
        self.sessao.add(unidade)
        self.sessao.flush()  # gera o id para a auditoria
        self._auditar(ator, "CADASTRAR_UNIDADE", "unidade", unidade.id, unidade.id, {"depois": dados.model_dump()}, ip)
        self.sessao.commit()
        self.sessao.refresh(unidade)  # ativa e criado_em vêm do banco
        return _view_unidade(unidade)

    def alterar_unidade(
        self, ator: Credencial, unidade_id: int, dados: v.UnidadeAlteracao, ip: str | None = None
    ) -> v.Unidade:
        unidade = self.sessao.get(UnidadeModel, unidade_id)
        if unidade is None:
            raise _nao_encontrado("Unidade")
        mudancas = _mudancas(dados)
        antes = {campo: getattr(unidade, campo) for campo in mudancas}
        for campo, valor in mudancas.items():
            if campo in ("horario_abertura", "horario_fechamento"):
                valor = _horario(campo, valor)
            setattr(unidade, campo, valor)
        self._auditar(
            ator, "ALTERAR_UNIDADE", "unidade", unidade.id, unidade.id, {"antes": antes, "depois": mudancas}, ip
        )
        self.sessao.commit()
        return _view_unidade(unidade)

    # ---- Catálogo padrão da matriz (RF04, D05) ----

    def listar_produtos(self, limit: int, offset: int) -> v.ListaProdutos:
        """Catálogo completo, inclusive inativos: é a visão de gestão da MATRIZ e do GERENTE."""
        total = self.sessao.scalar(select(func.count()).select_from(ProdutoModel))
        produtos = self.sessao.scalars(select(ProdutoModel).order_by(ProdutoModel.id).limit(limit).offset(offset))
        return v.ListaProdutos(itens=[_view_produto(p) for p in produtos], total=total)

    def cadastrar_produto(self, ator: Credencial, dados: v.ProdutoEntrada, ip: str | None = None) -> v.Produto:
        base, minimo, maximo = Decimal(dados.preco_base), Decimal(dados.preco_minimo), Decimal(dados.preco_maximo)
        _conferir_faixa(minimo, base, maximo)
        if self.sessao.scalar(select(ProdutoModel.id).where(ProdutoModel.codigo == dados.codigo)) is not None:
            raise _codigo_ja_cadastrado()
        produto = ProdutoModel(
            codigo=dados.codigo,
            nome=dados.nome,
            descricao=dados.descricao,
            categoria=dados.categoria,
            preco_base=base,
            preco_minimo=minimo,
            preco_maximo=maximo,
            exige_cozinha_completa=dados.exige_cozinha_completa,
        )
        self.sessao.add(produto)
        try:
            self.sessao.flush()  # gera o id; a chave única barra o cadastro simultâneo
            self._auditar(ator, "CADASTRAR_PRODUTO", "produto", produto.id, None, {"depois": dados.model_dump()}, ip)
            self.sessao.commit()
        except IntegrityError:  # cadastro simultâneo do mesmo código
            self.sessao.rollback()
            raise _codigo_ja_cadastrado() from None
        self.sessao.refresh(produto)  # ativo vem do banco
        return _view_produto(produto)

    def alterar_produto(
        self, ator: Credencial, produto_id: int, dados: v.ProdutoAlteracao, ip: str | None = None
    ) -> v.Produto:
        produto = self.sessao.get(ProdutoModel, produto_id)
        if produto is None:
            raise _nao_encontrado("Produto")
        mudancas = _mudancas(dados, anulaveis={"descricao"})
        for campo in ("preco_base", "preco_minimo", "preco_maximo"):
            if campo in mudancas:
                mudancas[campo] = Decimal(mudancas[campo])
        _conferir_faixa(
            mudancas.get("preco_minimo", produto.preco_minimo),
            mudancas.get("preco_base", produto.preco_base),
            mudancas.get("preco_maximo", produto.preco_maximo),
        )
        antes = {campo: getattr(produto, campo) for campo in mudancas}
        for campo, valor in mudancas.items():
            setattr(produto, campo, valor)
        self._auditar(
            ator, "ALTERAR_PRODUTO", "produto", produto.id, None, {"antes": antes, "depois": mudancas}, ip
        )
        self.sessao.commit()
        return _view_produto(produto)

    # ---- Cardápio da unidade (RF05, RF08) ----

    def consultar_cardapio(self, unidade_id: int) -> v.ListaItensCardapio:
        """Cardápio vigente: item disponível, produto ativo e compatível com a cozinha da unidade (RN01, RN02)."""
        unidade = self.sessao.get(UnidadeModel, unidade_id)
        if unidade is None or not unidade.ativa:  # unidade inativa não aparece para o cliente
            raise _nao_encontrado("Unidade")
        consulta = _cardapio_vigente(unidade).order_by(ProdutoModel.categoria, ProdutoModel.nome)
        itens = [_view_item(i) for i in self.sessao.scalars(consulta).unique()]
        return v.ListaItensCardapio(itens=itens, total=len(itens))

    # ---- Leituras usadas pelo domínio Pedidos (E12) ----

    def obter_unidade(self, unidade_id: int) -> UnidadeModel | None:
        return self.sessao.get(UnidadeModel, unidade_id)

    @staticmethod
    def esta_aberta(unidade: UnidadeModel, agora: datetime) -> bool:
        """RN05: unidade ativa e dentro do horário, na hora local (D70: fuso fixo America/Recife)."""
        if not unidade.ativa:
            return False
        hora = agora.astimezone(FUSO_UNIDADES).time()
        abre, fecha = unidade.horario_abertura, unidade.horario_fechamento
        if abre <= fecha:
            return abre <= hora < fecha
        return hora >= abre or hora < fecha  # horário que passa da meia-noite

    def itens_vendaveis(self, unidade: UnidadeModel, produto_ids: list[int]) -> dict[int, ItemCardapioModel]:
        """Itens do cardápio vigente entre os pedidos, por produto_id; o que faltar está indisponível."""
        consulta = _cardapio_vigente(unidade).where(ItemCardapioModel.produto_id.in_(produto_ids))
        return {i.produto_id: i for i in self.sessao.scalars(consulta).unique()}

    def definir_item_cardapio(
        self,
        ator: Credencial,
        unidade_id: int,
        produto_id: int,
        dados: v.ItemCardapioEntrada,
        ip: str | None = None,
    ) -> v.ItemCardapio:
        # Nível 2 (unidade): o GERENTE só altera a própria unidade; a MATRIZ, todas (RN12)
        if ator.perfil == Perfil.GERENTE and ator.unidade_id != unidade_id:
            raise ErroDominio("SEM_PERMISSAO", "Unidade diferente da do token")
        unidade = self.sessao.get(UnidadeModel, unidade_id)
        if unidade is None:
            raise _nao_encontrado("Unidade")
        produto = self.sessao.get(ProdutoModel, produto_id)
        if produto is None:
            raise _nao_encontrado("Produto")

        preco = Decimal(dados.preco)
        if not (produto.preco_minimo <= preco <= produto.preco_maximo):  # RN01
            raise ErroDominio(
                "PRECO_FORA_DA_FAIXA",
                "Preço local fora da faixa definida pela matriz",
                [
                    {
                        "campo": "preco",
                        "valor": dados.preco,
                        "problema": f"faixa permitida: {_dinheiro(produto.preco_minimo)} a {_dinheiro(produto.preco_maximo)}",
                    }
                ],
            )
        if produto.exige_cozinha_completa and unidade.tipo_operacao == TipoOperacao.REDUZIDA:  # RN02
            raise ErroDominio(
                "PRODUTO_INCOMPATIVEL_UNIDADE", "O produto exige cozinha completa e a unidade é REDUZIDA"
            )

        item = self.sessao.get(ItemCardapioModel, (unidade_id, produto_id))
        antes = None if item is None else {"preco": item.preco, "disponivel": item.disponivel}
        if item is None:
            item = ItemCardapioModel(unidade_id=unidade_id, produto_id=produto_id, produto=produto)
            self.sessao.add(item)
        item.preco = preco
        item.disponivel = dados.disponivel
        self._auditar(
            ator,
            "DEFINIR_ITEM_CARDAPIO",
            "produto",  # a chave do item é (unidade_id, produto_id): a unidade vai na coluna própria
            produto_id,
            unidade_id,
            {"antes": antes, "depois": {"preco": preco, "disponivel": dados.disponivel}},
            ip,
        )
        self.sessao.commit()
        return _view_item(item)


    # ---- Apoio ----

    def _auditar(
        self,
        ator: Credencial,
        acao: str,
        entidade: str,
        entidade_id: int,
        unidade_id: int | None,
        detalhes: dict,
        ip: str | None,
    ) -> None:
        AuditoriaService(self.sessao).registrar(
            acao, entidade, entidade_id, ator=ator, unidade_id=unidade_id, detalhes=detalhes, ip=ip
        )


def _cardapio_vigente(unidade: UnidadeModel):
    """Item disponível, produto ativo e compatível com a cozinha da unidade (RN01, RN02)."""
    consulta = (
        select(ItemCardapioModel)
        .join(ItemCardapioModel.produto)
        .where(
            ItemCardapioModel.unidade_id == unidade.id,
            ItemCardapioModel.disponivel.is_(True),
            ProdutoModel.ativo.is_(True),
        )
    )
    if unidade.tipo_operacao == TipoOperacao.REDUZIDA:
        consulta = consulta.where(ProdutoModel.exige_cozinha_completa.is_(False))
    return consulta


def _codigo_ja_cadastrado() -> ErroDominio:
    return ErroDominio("CODIGO_JA_CADASTRADO", "Já existe um produto com este código")
