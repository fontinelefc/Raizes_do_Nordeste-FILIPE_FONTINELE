-- =============================================================================
-- Raízes do Nordeste — esquema do banco (E10)
-- MySQL 8.0 ou superior · InnoDB · utf8mb4 · datas em UTC (M12)
--
-- Fonte: seção 3.3 do documento (classes, DER, enumerações e dicionário de
-- dados). São as 14 tabelas da D26/D30, com os mesmos nomes do dicionário.
--
-- ATENÇÃO: este script APAGA e recria o banco raizes_nordeste. Use só no
-- ambiente de desenvolvimento e de testes.
--
-- Execução (como root):  mysql -u root -p < sql/01_esquema.sql
-- =============================================================================

-- Sessão em utf8mb4, independente do idioma do sistema (ERR-006): sem isso, um
-- cliente mysql em latin1 converte os acentos duas vezes ("CafÃ© coado").
SET NAMES utf8mb4;

DROP DATABASE IF EXISTS raizes_nordeste;
CREATE DATABASE raizes_nordeste
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE raizes_nordeste;

-- Datas gravadas em UTC (M12): os valores padrão CURRENT_TIMESTAMP abaixo
-- seguem o fuso da sessão; a aplicação abre cada conexão com time_zone = '+00:00'.
SET time_zone = '+00:00';

-- -----------------------------------------------------------------------------
-- Organização e acesso
-- -----------------------------------------------------------------------------

-- unidade · RF03; RN02, RN05, RN12
CREATE TABLE unidade (
  id                  BIGINT       NOT NULL AUTO_INCREMENT,
  nome                VARCHAR(100) NOT NULL,
  tipo_operacao       ENUM('COMPLETA','REDUZIDA') NOT NULL,
  cidade              VARCHAR(80)  NOT NULL,
  uf                  CHAR(2)      NOT NULL,
  horario_abertura    TIME         NOT NULL,
  horario_fechamento  TIME         NOT NULL,
  ativa               BOOLEAN      NOT NULL DEFAULT TRUE,
  criado_em           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT pk_unidade PRIMARY KEY (id),
  CONSTRAINT ck_unidade_uf CHECK (REGEXP_LIKE(uf, '^[A-Z]{2}$', 'c'))
) ENGINE = InnoDB;

-- usuario · RF01, RF02; RN12  (funcionários; clientes ficam em cliente)
CREATE TABLE usuario (
  id          BIGINT       NOT NULL AUTO_INCREMENT,
  unidade_id  BIGINT       NULL,
  nome        VARCHAR(100) NOT NULL,
  email       VARCHAR(150) NOT NULL,
  senha_hash  VARCHAR(255) NOT NULL,
  perfil      ENUM('MATRIZ','GERENTE','ATENDENTE','COZINHA') NOT NULL,
  ativo       BOOLEAN      NOT NULL DEFAULT TRUE,
  criado_em   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT pk_usuario PRIMARY KEY (id),
  CONSTRAINT uq_usuario_email UNIQUE (email),
  CONSTRAINT fk_usuario_unidade FOREIGN KEY (unidade_id)
    REFERENCES unidade (id),
  -- RN12: MATRIZ não pertence a unidade; os demais perfis pertencem a uma
  CONSTRAINT ck_usuario_unidade_perfil CHECK (
    (perfil = 'MATRIZ' AND unidade_id IS NULL) OR
    (perfil <> 'MATRIZ' AND unidade_id IS NOT NULL)
  )
) ENGINE = InnoDB;

-- -----------------------------------------------------------------------------
-- Catálogo e estoque
-- -----------------------------------------------------------------------------

-- produto · RF04; RN01, RN02  (catálogo padrão da matriz)
CREATE TABLE produto (
  id                      BIGINT        NOT NULL AUTO_INCREMENT,
  codigo                  VARCHAR(20)   NOT NULL,
  nome                    VARCHAR(100)  NOT NULL,
  descricao               VARCHAR(255)  NULL,
  categoria               VARCHAR(50)   NOT NULL,
  preco_base              DECIMAL(10,2) NOT NULL,
  preco_minimo            DECIMAL(10,2) NOT NULL,
  preco_maximo            DECIMAL(10,2) NOT NULL,
  exige_cozinha_completa  BOOLEAN       NOT NULL DEFAULT FALSE,
  ativo                   BOOLEAN       NOT NULL DEFAULT TRUE,
  CONSTRAINT pk_produto PRIMARY KEY (id),
  CONSTRAINT uq_produto_codigo UNIQUE (codigo),
  -- RN01: faixa de preço coerente, com o preço base dentro dela
  CONSTRAINT ck_produto_faixa CHECK (
    preco_minimo > 0 AND preco_minimo <= preco_base AND preco_base <= preco_maximo
  )
) ENGINE = InnoDB;

-- item_cardapio · RF05, RF08; RN01, RN02  (M02: associativa unidade × produto)
-- A faixa preco_minimo–preco_maximo e a regra da cozinha completa (RN02)
-- envolvem outra tabela e são verificadas no UnidadeService.
CREATE TABLE item_cardapio (
  unidade_id     BIGINT        NOT NULL,
  produto_id     BIGINT        NOT NULL,
  preco          DECIMAL(10,2) NOT NULL,
  disponivel     BOOLEAN       NOT NULL DEFAULT TRUE,
  atualizado_em  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT pk_item_cardapio PRIMARY KEY (unidade_id, produto_id),
  CONSTRAINT fk_item_cardapio_unidade FOREIGN KEY (unidade_id)
    REFERENCES unidade (id),
  CONSTRAINT fk_item_cardapio_produto FOREIGN KEY (produto_id)
    REFERENCES produto (id),
  CONSTRAINT ck_item_cardapio_preco CHECK (preco > 0)
) ENGINE = InnoDB;

-- estoque · RF15; RN06  (M03: disponível = quantidade − quantidade_reservada)
CREATE TABLE estoque (
  unidade_id            BIGINT   NOT NULL,
  produto_id            BIGINT   NOT NULL,
  quantidade            INT      NOT NULL DEFAULT 0,
  quantidade_reservada  INT      NOT NULL DEFAULT 0,
  atualizado_em         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT pk_estoque PRIMARY KEY (unidade_id, produto_id),
  -- FK composta: só há estoque de produto que está no cardápio da unidade
  CONSTRAINT fk_estoque_item_cardapio FOREIGN KEY (unidade_id, produto_id)
    REFERENCES item_cardapio (unidade_id, produto_id),
  -- Última barreira para a reserva e a baixa (D27): nunca negativo, nunca
  -- reservado acima do saldo físico
  CONSTRAINT ck_estoque_saldo CHECK (
    quantidade >= 0 AND quantidade_reservada >= 0
    AND quantidade_reservada <= quantidade
  )
) ENGINE = InnoDB;

-- -----------------------------------------------------------------------------
-- Clientes, fidelidade e LGPD  (antes de pedido, que referencia cliente)
-- -----------------------------------------------------------------------------

-- cliente · RF01, RF17, RF20; RN17
CREATE TABLE cliente (
  id            BIGINT       NOT NULL AUTO_INCREMENT,
  nome          VARCHAR(100) NOT NULL,
  email         VARCHAR(150) NOT NULL,
  telefone      VARCHAR(20)  NULL,
  senha_hash    VARCHAR(255) NOT NULL,
  faixa_etaria  ENUM('MENOR_18','DE_18_A_24','DE_25_A_34','DE_35_A_44',
                     'DE_45_A_59','A_PARTIR_60') NULL,
  saldo_pontos  INT          NOT NULL DEFAULT 0,
  criado_em     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT pk_cliente PRIMARY KEY (id),
  CONSTRAINT uq_cliente_email UNIQUE (email),
  CONSTRAINT ck_cliente_saldo CHECK (saldo_pontos >= 0)
) ENGINE = InnoDB;

-- consentimento · RF20; RN16, RN17  (M09: cada aceite é uma nova linha)
CREATE TABLE consentimento (
  id                      BIGINT      NOT NULL AUTO_INCREMENT,
  cliente_id              BIGINT      NOT NULL,
  finalidade              ENUM('FIDELIDADE') NOT NULL,
  versao_termo            VARCHAR(10) NOT NULL,
  autorizado_responsavel  BOOLEAN     NOT NULL DEFAULT FALSE,
  concedido_em            DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revogado_em             DATETIME    NULL,
  CONSTRAINT pk_consentimento PRIMARY KEY (id),
  CONSTRAINT fk_consentimento_cliente FOREIGN KEY (cliente_id)
    REFERENCES cliente (id),
  CONSTRAINT ck_consentimento_revogacao CHECK (
    revogado_em IS NULL OR revogado_em >= concedido_em
  )
) ENGINE = InnoDB;

-- -----------------------------------------------------------------------------
-- Pedidos
-- -----------------------------------------------------------------------------

-- pedido · RF09–RF12; RN05–RN08, RN10
CREATE TABLE pedido (
  id             BIGINT        NOT NULL AUTO_INCREMENT,
  unidade_id     BIGINT        NOT NULL,
  cliente_id     BIGINT        NULL,          -- M07: NULL em pedido anônimo (D12)
  canal          ENUM('APP','TOTEM','BALCAO','PICKUP') NOT NULL,
  status         ENUM('AGUARDANDO_PAGAMENTO','PAGO','EM_PREPARO','PRONTO',
                      'ENTREGUE','PAGAMENTO_RECUSADO','EXPIRADO','CANCELADO')
                 NOT NULL DEFAULT 'AGUARDANDO_PAGAMENTO',
  valor_total    DECIMAL(10,2) NOT NULL,
  expira_em      DATETIME      NULL,          -- criado_em + 15 min (RN10, D08)
  criado_em      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT pk_pedido PRIMARY KEY (id),
  CONSTRAINT fk_pedido_unidade FOREIGN KEY (unidade_id)
    REFERENCES unidade (id),
  CONSTRAINT fk_pedido_cliente FOREIGN KEY (cliente_id)
    REFERENCES cliente (id),
  CONSTRAINT ck_pedido_valor CHECK (valor_total >= 0),
  -- fila da cozinha e painel da unidade (UC11)
  INDEX ix_pedido_unidade_status (unidade_id, status, criado_em),
  -- agendador de expiração (UC14, T4)
  INDEX ix_pedido_status_expira (status, expira_em)
) ENGINE = InnoDB;

-- item_pedido · RF09  (M08: o preço é copiado do cardápio no momento do pedido)
CREATE TABLE item_pedido (
  id              BIGINT        NOT NULL AUTO_INCREMENT,
  pedido_id       BIGINT        NOT NULL,
  produto_id      BIGINT        NOT NULL,
  quantidade      INT           NOT NULL,
  preco_unitario  DECIMAL(10,2) NOT NULL,
  subtotal        DECIMAL(10,2) NOT NULL,
  CONSTRAINT pk_item_pedido PRIMARY KEY (id),
  CONSTRAINT uq_item_pedido_produto UNIQUE (pedido_id, produto_id),
  CONSTRAINT fk_item_pedido_pedido FOREIGN KEY (pedido_id)
    REFERENCES pedido (id),
  CONSTRAINT fk_item_pedido_produto FOREIGN KEY (produto_id)
    REFERENCES produto (id),
  CONSTRAINT ck_item_pedido_valores CHECK (
    quantidade > 0 AND preco_unitario > 0
    AND subtotal = quantidade * preco_unitario
  )
) ENGINE = InnoDB;

-- historico_status_pedido · RF10–RF12; RN07  (M04: uma linha por transição)
CREATE TABLE historico_status_pedido (
  id               BIGINT       NOT NULL AUTO_INCREMENT,
  pedido_id        BIGINT       NOT NULL,
  status_anterior  ENUM('AGUARDANDO_PAGAMENTO','PAGO','EM_PREPARO','PRONTO',
                        'ENTREGUE','PAGAMENTO_RECUSADO','EXPIRADO','CANCELADO')
                   NULL,                     -- NULL no registro de criação
  status_novo      ENUM('AGUARDANDO_PAGAMENTO','PAGO','EM_PREPARO','PRONTO',
                        'ENTREGUE','PAGAMENTO_RECUSADO','EXPIRADO','CANCELADO')
                   NOT NULL,
  origem           ENUM('CLIENTE','FUNCIONARIO','SISTEMA','GATEWAY') NOT NULL,
  motivo           VARCHAR(255) NULL,
  criado_em        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT pk_historico_status_pedido PRIMARY KEY (id),
  CONSTRAINT fk_historico_pedido FOREIGN KEY (pedido_id)
    REFERENCES pedido (id),
  -- RF12: cancelamento exige justificativa
  CONSTRAINT ck_historico_motivo_cancelamento CHECK (
    status_novo <> 'CANCELADO' OR (motivo IS NOT NULL AND CHAR_LENGTH(motivo) >= 10)
  )
) ENGINE = InnoDB;

-- movimentacao_pontos · RF17; RN14  (M11: extrato; saldo em cliente.saldo_pontos)
CREATE TABLE movimentacao_pontos (
  id          BIGINT   NOT NULL AUTO_INCREMENT,
  cliente_id  BIGINT   NOT NULL,
  pedido_id   BIGINT   NULL,
  tipo        ENUM('CREDITO','ESTORNO') NOT NULL,
  pontos      INT      NOT NULL,
  criado_em   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT pk_movimentacao_pontos PRIMARY KEY (id),
  CONSTRAINT fk_movimentacao_cliente FOREIGN KEY (cliente_id)
    REFERENCES cliente (id),
  CONSTRAINT fk_movimentacao_pedido FOREIGN KEY (pedido_id)
    REFERENCES pedido (id),
  -- positivo no crédito, negativo no estorno
  CONSTRAINT ck_movimentacao_sinal CHECK (
    (tipo = 'CREDITO' AND pontos > 0) OR (tipo = 'ESTORNO' AND pontos < 0)
  )
) ENGINE = InnoDB;

-- -----------------------------------------------------------------------------
-- Pagamentos
-- -----------------------------------------------------------------------------

-- pagamento · RF13, RF14; RN09; D14, D24  (M05/D28: um pagamento por pedido)
CREATE TABLE pagamento (
  id                 BIGINT        NOT NULL AUTO_INCREMENT,
  pedido_id          BIGINT        NOT NULL,
  tipo               ENUM('ONLINE','BALCAO') NOT NULL,
  forma              ENUM('PIX','CARTAO_CREDITO','CARTAO_DEBITO','DINHEIRO') NOT NULL,
  valor              DECIMAL(10,2) NOT NULL,
  status             ENUM('PENDENTE','APROVADO','RECUSADO',
                          'ESTORNO_SOLICITADO','ESTORNADO')
                     NOT NULL DEFAULT 'PENDENTE',
  transacao_gateway  VARCHAR(100)  NULL,      -- NULL no balcão e até o gateway responder (D39)
  motivo_recusa      VARCHAR(255)  NULL,
  criado_em          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT pk_pagamento PRIMARY KEY (id),
  CONSTRAINT uq_pagamento_pedido UNIQUE (pedido_id),
  CONSTRAINT uq_pagamento_transacao UNIQUE (transacao_gateway),
  CONSTRAINT fk_pagamento_pedido FOREIGN KEY (pedido_id)
    REFERENCES pedido (id),
  CONSTRAINT ck_pagamento_valor CHECK (valor > 0),
  -- D14: dinheiro só no balcão; o balcão não passa pelo gateway
  CONSTRAINT ck_pagamento_tipo_forma CHECK (
    (tipo = 'ONLINE' AND forma <> 'DINHEIRO') OR
    (tipo = 'BALCAO' AND transacao_gateway IS NULL)
  )
) ENGINE = InnoDB;

-- evento_pagamento · RF14; D09  (M06/D28: idempotência do webhook)
CREATE TABLE evento_pagamento (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  evento_gateway  VARCHAR(100) NOT NULL,
  pagamento_id    BIGINT       NULL,
  tipo            VARCHAR(50)  NOT NULL,
  payload         JSON         NOT NULL,      -- sem dados de cartão (RN09)
  recebido_em     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processado_em   DATETIME     NULL,
  CONSTRAINT pk_evento_pagamento PRIMARY KEY (id),
  CONSTRAINT uq_evento_gateway UNIQUE (evento_gateway),
  CONSTRAINT fk_evento_pagamento FOREIGN KEY (pagamento_id)
    REFERENCES pagamento (id)
) ENGINE = InnoDB;

-- -----------------------------------------------------------------------------
-- Auditoria
-- -----------------------------------------------------------------------------

-- registro_auditoria · RF25; RN13  (M10: sem FK e somente inserção;
-- o usuário da aplicação só recebe SELECT e INSERT — ver 02_usuario_app.sql)
CREATE TABLE registro_auditoria (
  id           BIGINT      NOT NULL AUTO_INCREMENT,
  ator_tipo    ENUM('CLIENTE','FUNCIONARIO','SISTEMA','GATEWAY') NOT NULL,
  ator_id      BIGINT      NULL,
  acao         VARCHAR(50) NOT NULL,
  entidade     VARCHAR(50) NOT NULL,
  entidade_id  BIGINT      NULL,
  unidade_id   BIGINT      NULL,
  detalhes     JSON        NULL,              -- antes e depois, sem dados pessoais
  ip_origem    VARCHAR(45) NULL,
  criado_em    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT pk_registro_auditoria PRIMARY KEY (id),
  INDEX ix_auditoria_entidade (entidade, entidade_id)
) ENGINE = InnoDB;
