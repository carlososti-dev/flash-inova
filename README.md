# Flash Inova — app de campanhas de ideias

Fatia 1: base para vários hospitais, login por e-mail e identidade de cada hospital.
Fatia 2: lista de autorizados, primeiro acesso por matrícula e e-mail, gestão de usuários.

- **Backend**: Python, FastAPI, SQLAlchemy, PostgreSQL (`backend/`)
- **Frontend**: React + Vite + TypeScript (`frontend/`)
- Especificações na pasta acima: `Inicio.md`, `Form_Projeto.md`, `pagina1.md` (modelo de dados), `Fases_Campanha.md`, `Regras_da_POC.md`.

## O que já funciona

- **Hospital pelo endereço**: `hnsg.<domínio>` abre o HNSG. Em desenvolvimento, use `?tenant=hnsg` na URL.
- **Login por e-mail e senha** para todos os perfis (Consultor, Administrador, Gestor, Membro de comitê, Colaborador).
- **Ativação de conta por link no e-mail**: a pessoa confirma o e-mail e cria a senha. Sem confirmar, não entra.
- **Esqueci minha senha**: link de uso único, válido por 1 hora; ao trocar a senha, as sessões abertas caem.
- **Área do Consultor** (`/plataforma`): criar hospital, enviar logotipo, escolher tema verde ou azul, suspender acesso e criar o primeiro administrador.
- **Isolamento entre hospitais em duas camadas**: a aplicação filtra pelo hospital e o PostgreSQL recusa linhas de outro hospital (Row Level Security), mesmo se um filtro for esquecido.
- **Auditoria**: logins, trocas de senha e toda ação do Consultor ficam em `audit_log`.
- **Lista de autorizados** (Administração): importação de planilha CSV ou XLSX com conferência antes de gravar e relatório de erros por linha; modelo para baixar; inclusão manual; busca; desativar e reativar. Quem já está na lista é atualizado pela matrícula, e ninguém é removido por ficar fora do arquivo.
- **Primeiro acesso** (`/cadastro`): a pessoa informa matrícula e e-mail; se conferirem com a lista, recebe o link para criar a senha e nasce com o perfil inicial da lista (colaborador, se vazio). A resposta é sempre a mesma, para não revelar quem está na lista. Quem já tem conta recebe o link de redefinição.
- **Usuários** (Administração): busca e filtros, troca de perfil, desativar (derruba as sessões abertas) e reativar, reenviar convite. O administrador não altera a si mesmo, e o perfil Consultor não pode ser dado.
- Menu da página inicial conforme a especificação: Análise para administrador, consultor e comitê; Classificação e Administração para administrador e consultor.

## Rodar localmente

Pré-requisitos: Docker, Python 3.12+ e Node 20+.

```bash
# 1. Banco
docker compose up -d

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head                      # cria as tabelas (usa MIGRATIONS_DATABASE_URL do .env)
python -m app.cli criar-consultor --nome "Seu Nome" --email voce@empresa.com.br
uvicorn app.main:app --reload --port 8000

# 3. Frontend (outro terminal)
cd frontend
npm install
npm run dev
```

Ao receber uma versão nova, rode de novo `pip install -r requirements-dev.txt` e `alembic upgrade head` (com o `.venv` ativo).

Abra http://localhost:5173/login, entre como Consultor, crie um hospital e um administrador.
Em desenvolvimento os e-mails aparecem **no terminal do backend**: copie de lá o link de ativação.

## Testes

```bash
cd backend
TEST_ADMIN_DATABASE_URL=postgresql+psycopg://flash_owner:flash_owner@localhost:5433/postgres pytest
```

Os testes criam um banco próprio (`flash_inova_test`) num PostgreSQL de verdade, porque o isolamento entre hospitais depende do RLS.
Cobrem: importação da lista (conferência, erros por linha, XLSX, reimportação), cadastro pela lista, gestão de usuários, login, senha errada, conta não confirmada, usuário inativo, hospital suspenso, usuário e sessão de um hospital tentando entrar em outro, redefinição de senha (uso único, expiração, link de outro hospital), permissões da área do Consultor, logotipo (SVG recusado) e o RLS direto no banco.

## Pendências conhecidas

- **E-mail em produção**: hoje só existe o envio no terminal (`ConsoleEmailSender`). Falta ligar um serviço transacional (SendGrid, SES, Gmail) atrás da mesma interface em `app/email.py`.
- **Arquivos em produção**: logotipos vão para a pasta `storage/`. Falta a implementação para Cloud Storage em `app/storage.py`.
- **Limite de tentativas** de login e de primeiro acesso (proteção contra força bruta): ainda não implementado.
- **Matrícula com zero à esquerda** em XLSX: se a coluna estiver formatada como número no Excel, o zero se perde. Formate a coluna como texto ou use CSV.
- **Migrações e deploy** no Google Cloud (Cloud Run + Cloud SQL): a definir.

## Próximas fatias

3. Campanhas: datas das fases, linhas de ideias, textos, banner, vídeo e regras.
Depois: envio de ideias, distribuição duplo-cego, análise, classificação, defesa, votação e resultados.
