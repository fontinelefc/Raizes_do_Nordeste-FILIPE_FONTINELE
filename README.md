API-Raízes do Nordeste

API REST da rede de restaurantes Raízes do Nordeste, desenvolvido como parte do
Projeto Multidisciplinar do curso de Análise e Desenvolvimento de Sistemas (Uninter),
trilha Back-end.

A API atende os quatro canais de venda (app, totem, balcão e pick-up), o cardápio e o
estoque de cada unidade, o pagamento por um gateway externo (simulado) com webhook
idempotente, o programa de fidelidade com consentimento conforme a LGPD e a trilha de
auditoria das operações sensíveis.

Pré-requisitos

- Python 3 (desenvolvido com o Python 3.13 e testado também no 3.14)
- MySQL Server 8.0 ou superior
- Git

sudo dnf install python3 git mysql-server
sudo systemctl enable --now mysqld


Criar o ambiente Python


python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

Criar o banco

Antes, abra sql/02_usuario_app.sql e use a senha "H16f10@12".
Rodar os três scripts nesta ordem, como usuário root do MySQL:

mysql -u root -p < sql/01_esquema.sql
mysql -u root -p < sql/02_usuario_app.sql
mysql -u root -p < sql/03_dados_exemplo.sql


Configurar as variáveis de ambiente

cp .env.example .env

Edite o .env: coloque em DB_SENHA a mesma senha e gere valores
aleatórios para os segredos.

Rodar os testes


pytest -v


Subir a API


uvicorn app.main:app --reload


- Documentação interativa (Swagger): http://localhost:8000/docs
- Contrato gerado pela aplicação: http://localhost:8000/openapi.json
- Prefixo de todas as rotas: `/api/v1`

Autor

FILIPE FONTINELE · RU 4440979 · Análise e Desenvolvimento de Sistemas · Uninter
