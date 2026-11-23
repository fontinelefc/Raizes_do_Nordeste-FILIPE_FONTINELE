"""EstoqueService: saldo por unidade, reserva e devolução (RF15; RN06; D06, D25, D27, D45).

Dono da tabela ``estoque``. A carga inicial vem do script SQL (D45); a API só
consulta, reserva, libera, devolve e dá baixa (T2, E13).

Concorrência (D27): toda mudança de saldo é um ``UPDATE`` condicional atômico.
A reserva só afeta a linha se houver saldo disponível; se não afetar nenhuma,
o saldo acabou, e o pedido inteiro é desfeito. O ``CHECK ck_estoque_saldo`` do
banco é a última barreira.

Regra de transação (D52-5): só ``listar`` é chamado direto pelo controller; os
demais métodos são chamados pelo PedidoService (que, no T2 e no T3, é chamado
pelo PagamentoService), usam a mesma sessão e não fazem COMMIT.
"""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.enums import Perfil
from app.models.estoque import Estoque as EstoqueModel
from app.nucleo.erros import ErroDominio
from app.nucleo.seguranca import Credencial
from app.services.unidades import UnidadeService
from app.views import estoque as v

# (campo do corpo, produto_id, quantidade), ex.: ("itens[0].produto_id", 2, 3)
ItemReserva = tuple[str, int, int]


def _atualizar(sessao: Session, unidade_id: int, produto_id: int, condicao, **valores) -> bool:
    resultado = sessao.execute(
        update(EstoqueModel)
        .where(EstoqueModel.unidade_id == unidade_id, EstoqueModel.produto_id == produto_id, condicao)
        .values(**valores)
        .execution_options(synchronize_session=False)
    )
    return resultado.rowcount == 1


class EstoqueService:
    def __init__(self, sessao: Session) -> None:
        self.sessao = sessao

    def listar(self, ator: Credencial, unidade_id: int, limit: int, offset: int) -> v.ListaEstoque:
        """GERENTE da própria unidade ou MATRIZ (nível 2 da 3.6.5, RN12)."""
        if ator.perfil == Perfil.GERENTE and ator.unidade_id != unidade_id:
            raise ErroDominio("SEM_PERMISSAO", "Unidade diferente da do token")
        if UnidadeService(self.sessao).obter_unidade(unidade_id) is None:
            raise ErroDominio("NAO_ENCONTRADO", "Unidade não encontrada")
        filtro = EstoqueModel.unidade_id == unidade_id
        total = self.sessao.scalar(select(func.count()).select_from(EstoqueModel).where(filtro))
        linhas = self.sessao.scalars(
            select(EstoqueModel).where(filtro).order_by(EstoqueModel.produto_id).limit(limit).offset(offset)
        )
        itens = [
            v.Estoque(
                produto_id=e.produto_id,
                quantidade=e.quantidade,
                quantidade_reservada=e.quantidade_reservada,
                disponivel=e.quantidade - e.quantidade_reservada,
                atualizado_em=e.atualizado_em,
            )
            for e in linhas
        ]
        return v.ListaEstoque(itens=itens, total=total)

    def reservar(self, unidade_id: int, itens: list[ItemReserva]) -> None:
        """T1 (RN06): reserva cada item ou lança ESTOQUE_INSUFICIENTE; quem chama desfaz a transação.

        Os itens seguem a ordem de ``produto_id`` para que dois pedidos simultâneos
        travem as linhas na mesma ordem e não entrem em deadlock.
        """
        for campo, produto_id, quantidade in sorted(itens, key=lambda item: item[1]):
            reservou = _atualizar(
                self.sessao,
                unidade_id,
                produto_id,
                EstoqueModel.quantidade - EstoqueModel.quantidade_reservada >= quantidade,
                quantidade_reservada=EstoqueModel.quantidade_reservada + quantidade,
            )
            if not reservou:
                disponivel = self.sessao.scalar(
                    select(EstoqueModel.quantidade - EstoqueModel.quantidade_reservada).where(
                        EstoqueModel.unidade_id == unidade_id, EstoqueModel.produto_id == produto_id
                    )
                )
                raise ErroDominio(
                    "ESTOQUE_INSUFICIENTE",
                    "Saldo insuficiente para um ou mais itens",
                    [{"campo": campo, "valor": produto_id, "problema": f"saldo disponível: {disponivel or 0}"}],
                )

    def liberar(self, unidade_id: int, itens: list[tuple[int, int]]) -> None:
        """T3, T4, T5: devolve a reserva ao disponível (o saldo físico não muda)."""
        for produto_id, quantidade in sorted(itens):
            liberou = _atualizar(
                self.sessao,
                unidade_id,
                produto_id,
                EstoqueModel.quantidade_reservada >= quantidade,
                quantidade_reservada=EstoqueModel.quantidade_reservada - quantidade,
            )
            if not liberou:  # reserva menor que a do pedido: inconsistência, vira 500 e desfaz
                raise RuntimeError(f"reserva inconsistente: unidade {unidade_id}, produto {produto_id}")

    def baixar(self, unidade_id: int, itens: list[tuple[int, int]]) -> None:
        """T2 (D06): pagamento aprovado; a reserva vira saída do saldo físico."""
        for produto_id, quantidade in sorted(itens):
            baixou = _atualizar(
                self.sessao,
                unidade_id,
                produto_id,
                (EstoqueModel.quantidade_reservada >= quantidade) & (EstoqueModel.quantidade >= quantidade),
                quantidade=EstoqueModel.quantidade - quantidade,
                quantidade_reservada=EstoqueModel.quantidade_reservada - quantidade,
            )
            if not baixou:  # sem a reserva do pedido: inconsistência, vira 500 e desfaz
                raise RuntimeError(f"reserva inconsistente: unidade {unidade_id}, produto {produto_id}")

    def devolver(self, unidade_id: int, itens: list[tuple[int, int]]) -> None:
        """T9 (D25): pedido PAGO cancelado antes do preparo; o que saiu na baixa volta ao saldo."""
        for produto_id, quantidade in sorted(itens):
            devolveu = _atualizar(
                self.sessao,
                unidade_id,
                produto_id,
                EstoqueModel.quantidade >= 0,
                quantidade=EstoqueModel.quantidade + quantidade,
            )
            if not devolveu:
                raise RuntimeError(f"estoque ausente: unidade {unidade_id}, produto {produto_id}")
