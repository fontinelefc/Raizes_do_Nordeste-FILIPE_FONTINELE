"""AcessoService: login de funcionário e de cliente e cadastro de cliente (RF01, RF02, UC16).

Dono da tabela ``usuario``. O cliente é gravado pelo FidelidadeService, dono
da tabela ``cliente`` (D52-7).
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.usuario import Usuario
from app.nucleo.erros import ErroDominio
from app.nucleo.seguranca import Credencial, conferir_senha, gerar_hash, gerar_token
from app.services.fidelidade import FidelidadeService
from app.views.acesso import Cliente, ClienteEntrada, LoginEntrada, Token


class AcessoService:
    def __init__(self, sessao: Session, jwt_segredo: str) -> None:
        self.sessao = sessao
        self.jwt_segredo = jwt_segredo

    def login(self, dados: LoginEntrada) -> Token:
        """E-mail inexistente, senha errada e conta inativa dão a mesma resposta (3.6.3)."""
        if dados.tipo == "FUNCIONARIO":
            usuario = self.sessao.scalar(select(Usuario).where(Usuario.email == dados.email))
            valido = conferir_senha(dados.senha, usuario.senha_hash if usuario else None)
            if not (valido and usuario.ativo):
                raise _credenciais_invalidas()
            credencial = Credencial("FUNCIONARIO", usuario.id, usuario.perfil, usuario.unidade_id)
        else:
            cliente = FidelidadeService(self.sessao).buscar_cliente_por_email(dados.email)
            if not conferir_senha(dados.senha, cliente.senha_hash if cliente else None):
                raise _credenciais_invalidas()
            credencial = Credencial("CLIENTE", cliente.id)

        token, expira_em = gerar_token(credencial, self.jwt_segredo)
        return Token(
            access_token=token,
            expira_em=expira_em,
            perfil=credencial.perfil,
            unidade_id=credencial.unidade_id,
        )

    def cadastrar_cliente(self, dados: ClienteEntrada) -> Cliente:
        try:
            cliente = FidelidadeService(self.sessao).criar_cliente(
                nome=dados.nome,
                email=dados.email,
                telefone=dados.telefone,
                senha_hash=gerar_hash(dados.senha),
                faixa_etaria=dados.faixa_etaria,
            )
            self.sessao.commit()  # D52-5: o service chamado pelo controller confirma
        except (ErroDominio, IntegrityError):
            self.sessao.rollback()
            raise
        return Cliente.model_validate(cliente, from_attributes=True)


def _credenciais_invalidas() -> ErroDominio:
    return ErroDominio("CREDENCIAIS_INVALIDAS", "E-mail ou senha inválidos")
