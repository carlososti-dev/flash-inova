# Flash Inova — app de campanhas de ideias

Fatia 1: base para vários hospitais, login por e-mail e identidade de cada hospital.
Fatia 2: lista de autorizados, primeiro acesso por matrícula e e-mail, gestão de usuários.
Fatia 3: campanhas (datas das fases, linhas de ideias, textos, banner, vídeo, regulamento e regras) e a página inicial da campanha.
Fatia 4: envio de ideias (formulário configurável, rascunho e envio, coautores, aceite do regulamento), Minhas ideias e o kanban da Classificação.
Fatia 5: distribuição das ideias para o comitê e o menu Análise (parecer de cada avaliador).
Fatia 6: Classificação (apuração da POC, ranking com linha de corte e Voto de Minerva) e Dashboard dos avaliadores, com alerta por e-mail.

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
- **Campanhas** (Administração > Campanhas): várias por hospital, cada uma com título, datas de todas as fases (inscrição, análise, classificação, defesa e votação), chamada, apresentação, dicas, vídeo do YouTube, banner, regulamento e regras (avaliadores por ideia, pesos, linha de corte, duplo-cego, N finalistas da defesa, X da votação e número de premiadas). As regras de avaliação nascem com os padrões do hospital. Datas fora de ordem são recusadas com mensagem clara.
- **Linhas de ideias (temáticas)**: até 5 ativas por campanha, com descrição opcional, ordem ajustável, desativar e reativar. A campanha só é publicada com pelo menos uma linha ativa.
- **Rascunho e publicação**: só campanhas publicadas aparecem para os colaboradores; o administrador pré-visualiza o rascunho em "Ver página". Rascunho pode ser excluído; campanha publicada, não.
- **Página inicial da campanha**: banner (ou o título sobre a cor do hospital), período de inscrição ou "Inscrições de projetos encerradas", vídeo, dicas, temáticas, calendário das fases, link para o regulamento e botão "Enviar projeto", liberado só durante as inscrições. Mostra a campanha publicada mais recente que ainda não foi encerrada.
- **Formulário de envio configurável** (Administração > Campanhas > Formulário de envio): título, linha de ideias e resumo fixos; campos de texto curto, texto longo, lista de opções, sim/não e anexo, com rótulo, ajuda, obrigatório e ordem. Campo com respostas só é desativado.
- **Envio de ideias**: "Salvar rascunho" (só o autor vê) e "Enviar" (só durante as inscrições). A ideia enviada ganha um número (#1, #2…) e pode ser editada até o fim das inscrições, sem ficar incompleta. Anexos (PDF, imagem, Word, Excel, PowerPoint, até 10 MB) ficam fora da pasta pública e só saem pela API, para quem pode ver a ideia.
- **Coautores** da lista de autorizados (busca por nome ou matrícula, até 10); veem a ideia depois de enviada, sem editar.
- **Aceite do regulamento**: obrigatório para enviar; cada texto salvo do regulamento vira uma versão, e a ideia guarda a versão aceita e a data.
- **Minhas ideias**: as ideias da pessoa (autora ou coautora) e a etapa de cada uma.
- **Classificação (kanban)** para administrador, consultor e gestor: colunas Recebidas → Em análise → Empate → Classificadas / Talvez / Não classificadas → Shortlist → Selecionadas → Premiadas. Os cartões não são arrastados; mudam pelas ações do processo (nesta fatia, só "Recebidas" recebe cartões).
- **Distribuição para o comitê** (Administração > Campanhas > Configurar): depois do fim das inscrições, o administrador distribui as ideias recebidas. Cada uma vai para N membros do comitê (regra "avaliadores por ideia"), escolhidos pela menor carga; empate vai para quem recebeu há mais tempo. Ninguém avalia ideia de que é autor ou coautor. As ideias passam para "Em análise" e a campanha para a fase Análise.
- **Menu Análise** (membro de comitê): kanban pessoal com Para análise, Classificadas, Não classificadas e Talvez. Só mostra ideias depois da distribuição. No duplo-cego o avaliador não vê autor nem coautores. "Talvez" exige comentário. Dentro do período da análise (datas da campanha) o avaliador pode reavaliar ou desfazer o parecer quantas vezes quiser; fora dele, só lê. Todo parecer fica na auditoria. Administrador e consultor veem no mesmo menu todas as avaliações da campanha (um cartão por ideia e avaliador, com filtro por avaliador), só para acompanhar.

- **Dashboard** (administrador e consultor): pareceres dados e pendentes, prazo da análise e, por avaliador, quantas ideias faltam, último parecer e último alerta; por ideia, quem ainda não deu parecer. Enquanto a análise está aberta, o administrador envia um **alerta por e-mail** a todos com pendência ou só aos selecionados, com mensagem opcional. Cada alerta fica na auditoria.
- **Classificação › Apuração e ranking**: durante a análise mostra a prévia com os pareceres dados até agora. Depois do fim da análise, o administrador **apura** uma única vez, com a regra da prova de conceito: a favor (Classificar + Talvez) contra Não classificar; mais a favor vira Classificada (ou Talvez, se Talvez ≥ Classificar), mais contra vira Não classificada, empate vai para o Voto de Minerva. Pareceres em branco não contam. A nota de 0 a 100 ordena o ranking (desempate pelos pontos com os pesos da campanha). A campanha passa para a fase Classificação.
- **Voto de Minerva**: só o administrador, com justificativa obrigatória. O voto entra como um parecer a mais, desfaz o empate e define a nota. Pode ser revisto enquanto a campanha estiver na Classificação; tudo fica na auditoria. O autor não vê o empate (para ele, "Em classificação").
- **Linha de corte** editável na própria tela, ranking com a linha marcada e exportação em CSV. O gestor acompanha o ranking sem apurar nem votar. Os cartões do kanban mostram a nota.

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

Depois: distribuição duplo-cego, análise, classificação, defesa, votação e resultados.
