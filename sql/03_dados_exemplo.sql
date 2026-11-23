-- =============================================================================
-- Raízes do Nordeste — carga de exemplo (E10, D45)
--
-- Dados fictícios para demonstração e testes. Os ids são fixos para que os
-- testes e a coleção Postman possam usá-los.
--
--   * 3 unidades: Recife (COMPLETA), Fortaleza (REDUZIDA) e Salvador (inativa)
--   * 7 funcionários: MATRIZ + GERENTE, ATENDENTE e COZINHA em Recife e Fortaleza
--   * 7 produtos: um exige cozinha completa (RN02) e um está inativo
--   * cardápio e estoque por unidade, com saldos pequenos para testar
--     ESTOQUE_INSUFICIENTE (D45)
--   * 2 clientes: um adulto com consentimento e um menor de 18 sem consentimento
--
-- Senha de todas as contas de exemplo: Raizes@2026 (hash bcrypt, custo 12, D18).
-- Nenhum dado real de pessoa.
--
-- Execução (como root, depois do 01 e do 02):
--   mysql -u root -p < sql/03_dados_exemplo.sql
-- =============================================================================

-- Sessão em utf8mb4, independente do idioma do sistema (ERR-006): sem isso, um
-- cliente mysql em latin1 converte os acentos duas vezes ("CafÃ© coado").
SET NAMES utf8mb4;

USE raizes_nordeste;
SET time_zone = '+00:00';

SET @senha = '$2b$12$LUAAc0OahtCTIrwwM91uxuMkTEB3bk4AcOBPYOPaZQC0XsPCFnGW.';

-- Unidades ---------------------------------------------------------------------
INSERT INTO unidade (id, nome, tipo_operacao, cidade, uf,
                     horario_abertura, horario_fechamento, ativa) VALUES
  (1, 'Raízes Recife — Boa Viagem', 'COMPLETA', 'Recife',    'PE', '06:00', '22:00', TRUE),
  (2, 'Raízes Fortaleza — Aldeota', 'REDUZIDA', 'Fortaleza', 'CE', '07:00', '21:00', TRUE),
  (3, 'Raízes Salvador — Barra',    'COMPLETA', 'Salvador',  'BA', '06:00', '22:00', FALSE);

-- Funcionários (RN12: MATRIZ sem unidade) ---------------------------------------
INSERT INTO usuario (id, unidade_id, nome, email, senha_hash, perfil) VALUES
  (1, NULL, 'Ana Matriz',        'matriz@raizes.example',              @senha, 'MATRIZ'),
  (2, 1,    'Bruno Gerente',     'gerente.recife@raizes.example',      @senha, 'GERENTE'),
  (3, 1,    'Carla Atendente',   'atendente.recife@raizes.example',    @senha, 'ATENDENTE'),
  (4, 1,    'Davi Cozinha',      'cozinha.recife@raizes.example',      @senha, 'COZINHA'),
  (5, 2,    'Elisa Gerente',     'gerente.fortaleza@raizes.example',   @senha, 'GERENTE'),
  (6, 2,    'Fábio Atendente',   'atendente.fortaleza@raizes.example', @senha, 'ATENDENTE'),
  (7, 2,    'Gabi Cozinha',      'cozinha.fortaleza@raizes.example',   @senha, 'COZINHA');

-- Catálogo padrão da matriz (RN01: preco_minimo <= preco_base <= preco_maximo) ---
INSERT INTO produto (id, codigo, nome, descricao, categoria,
                     preco_base, preco_minimo, preco_maximo,
                     exige_cozinha_completa, ativo) VALUES
  (1, 'TAP-001', 'Tapioca de carne de sol', 'Tapioca recheada com carne de sol e queijo coalho', 'pratos',     18.90, 15.00, 24.00, FALSE, TRUE),
  (2, 'BAI-001', 'Baião de dois',           'Arroz, feijão-verde, queijo coalho e nata',          'pratos',     32.90, 28.00, 40.00, TRUE,  TRUE),
  (3, 'CUS-001', 'Cuscuz nordestino',       'Cuscuz de milho com ovo e manteiga da terra',        'pratos',     14.90, 12.00, 19.00, FALSE, TRUE),
  (4, 'SUC-001', 'Suco de cajá',            'Suco natural, 400 ml',                               'bebidas',     9.90,  8.00, 13.00, FALSE, TRUE),
  (5, 'CAF-001', 'Café coado',              'Café regional, 200 ml',                              'bebidas',     5.50,  4.50,  7.50, FALSE, TRUE),
  (6, 'BOL-001', 'Bolo de rolo (fatia)',    'Fatia de bolo de rolo com goiabada',                 'sobremesas',  8.90,  7.00, 12.00, FALSE, TRUE),
  (7, 'CAN-001', 'Canjica',                 'Produto sazonal (período junino)',                   'sobremesas', 10.90,  9.00, 14.00, FALSE, FALSE);

-- Cardápio por unidade (M02) ------------------------------------------------------
-- Recife (COMPLETA): todos os produtos ativos; preço local dentro da faixa.
-- Fortaleza (REDUZIDA): sem o Baião de dois, que exige cozinha completa (RN02);
-- suco indisponível no momento.
INSERT INTO item_cardapio (unidade_id, produto_id, preco, disponivel) VALUES
  (1, 1, 18.90, TRUE),
  (1, 2, 32.90, TRUE),
  (1, 3, 14.90, TRUE),
  (1, 4,  9.90, TRUE),
  (1, 5,  5.50, TRUE),
  (1, 6,  8.90, TRUE),
  (2, 1, 19.90, TRUE),
  (2, 3, 13.90, TRUE),
  (2, 4, 10.50, FALSE),
  (2, 5,  5.00, TRUE),
  (2, 6,  9.50, TRUE);

-- Estoque inicial (D45; a API só consulta, reserva e dá baixa) --------------------
-- Saldos pequenos de propósito: Baião de dois em Recife (3) e Bolo de rolo em
-- Fortaleza (2) servem aos testes de ESTOQUE_INSUFICIENTE.
INSERT INTO estoque (unidade_id, produto_id, quantidade, quantidade_reservada) VALUES
  (1, 1, 50, 0),
  (1, 2,  3, 0),
  (1, 3, 40, 0),
  (1, 4, 30, 0),
  (1, 5, 80, 0),
  (1, 6, 20, 0),
  (2, 1, 30, 0),
  (2, 3, 25, 0),
  (2, 4,  0, 0),
  (2, 5, 60, 0),
  (2, 6,  2, 0);

-- Clientes (RN17: faixa etária, sem data de nascimento) ---------------------------
INSERT INTO cliente (id, nome, email, telefone, senha_hash, faixa_etaria) VALUES
  (1, 'Maria Cliente', 'maria@cliente.example', '(85) 90000-0001', @senha, 'DE_25_A_34'),
  (2, 'João Cliente',  'joao@cliente.example',  NULL,              @senha, 'MENOR_18');

-- Consentimento vigente da Maria para o programa de fidelidade (RN16, M09).
-- O João (MENOR_18) fica sem consentimento: serve ao teste de
-- AUTORIZACAO_RESPONSAVEL_OBRIGATORIA.
INSERT INTO consentimento (id, cliente_id, finalidade, versao_termo,
                           autorizado_responsavel) VALUES
  (1, 1, 'FIDELIDADE', '1.0', FALSE);
