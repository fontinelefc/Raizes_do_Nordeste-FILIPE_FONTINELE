-- =============================================================================
-- Raízes do Nordeste — usuário do banco usado pela API (E10)
--
-- Privilégio mínimo:
--   * nenhuma permissão de DDL (CREATE, ALTER, DROP) nem de DELETE: nenhum
--     registro com histórico é apagado (seção 3.3.5);
--   * registro_auditoria só recebe SELECT e INSERT (M10, RN13): a própria
--     aplicação não consegue alterar nem apagar a trilha de auditoria.
--
-- ANTES DE EXECUTAR: troque a senha abaixo e use a mesma no DB_SENHA do .env.
--
-- Execução (como root, depois do 01_esquema.sql):
--   mysql -u root -p < sql/02_usuario_app.sql
-- =============================================================================

DROP USER IF EXISTS 'raizes_app'@'localhost';
CREATE USER 'raizes_app'@'localhost' IDENTIFIED BY 'H16f10@12';

-- Tabelas de negócio: ler, inserir e atualizar
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.unidade                 TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.usuario                 TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.produto                 TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.item_cardapio           TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.estoque                 TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.cliente                 TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.consentimento           TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.pedido                  TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.item_pedido             TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.historico_status_pedido TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.movimentacao_pontos     TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.pagamento               TO 'raizes_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON raizes_nordeste.evento_pagamento        TO 'raizes_app'@'localhost';

-- Auditoria: somente inserção e leitura (M10)
GRANT SELECT, INSERT ON raizes_nordeste.registro_auditoria TO 'raizes_app'@'localhost';
