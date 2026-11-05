# Implantação no Google Cloud (São Paulo)

Tudo fica na região `southamerica-east1` (São Paulo): os dados das instituições não saem do Brasil.

| Peça | Serviço | Custo aproximado/mês |
|---|---|---|
| App (API + telas) | Cloud Run, 1 serviço, escala até zero | US$ 0 a 10 no início |
| Banco PostgreSQL 16 | Cloud SQL, `db-g1-small`, 10 GB SSD, backup diário e recuperação ponto a ponto | US$ 30 a 35 |
| Arquivos (logos, banners, anexos) | Cloud Storage, bucket privado | menos de US$ 1 |
| Endereço com subdomínio por cliente e HTTPS | Load Balancer global + certificado curinga | US$ 18 a 20 |
| Senhas e chaves | Secret Manager | menos de US$ 1 |
| E-mail | Amazon SES (região São Paulo) | US$ 0,10 por mil e-mails |

Total no início: cerca de **US$ 55 a 70 por mês** (R$ 300 a 400). Cresce com o uso, não com o número de clientes.

Nos exemplos: domínio `inova.flashresponse.com.br`, então cada cliente fica em `<sigla>.inova.flashresponse.com.br`
e a Área do Consultor em `inova.flashresponse.com.br`. Troque se escolher outro domínio.

Os comandos rodam no **Cloud Shell** (ícone `>_` no topo do console.cloud.google.com), que já tem `gcloud` e `docker`.

## 0. Variáveis

```bash
export PROJECT=flash-inova-prod          # crie o projeto no console com este ID
export REGION=southamerica-east1
export DOMAIN=inova.flashresponse.com.br
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com compute.googleapis.com certificatemanager.googleapis.com
```

## 1. Banco (Cloud SQL)

```bash
gcloud sql instances create flash-db --database-version=POSTGRES_16 --region=$REGION \
  --tier=db-g1-small --storage-size=10 --storage-auto-increase \
  --backup-start-time=05:00 --enable-point-in-time-recovery --retained-backups-count=30 \
  --deletion-protection
gcloud sql databases create flash_inova --instance=flash-db
gcloud sql users create flash_owner --instance=flash-db --password="$(openssl rand -base64 24)"   # anote a senha
```

O usuário da aplicação **não pode** ser o dono das tabelas, senão o Row Level Security não vale.
Crie-o pelo dono (`gcloud sql connect flash-db --user=flash_owner --database=flash_inova`):

```sql
CREATE ROLE flash_app LOGIN PASSWORD 'SENHA_FORTE_DO_APP' NOSUPERUSER NOBYPASSRLS;
GRANT CONNECT ON DATABASE flash_inova TO flash_app;
GRANT USAGE ON SCHEMA public TO flash_app;
```

## 2. Arquivos (Cloud Storage)

```bash
gcloud storage buckets create gs://$PROJECT-arquivos --location=$REGION \
  --uniform-bucket-level-access --public-access-prevention
```

O bucket é privado: o app lê e entrega os arquivos, conferindo quem pode ver os anexos.

## 3. Conta de serviço e segredos

```bash
gcloud iam service-accounts create flash-app
SA=flash-app@$PROJECT.iam.gserviceaccount.com
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/cloudsql.client
gcloud storage buckets add-iam-policy-binding gs://$PROJECT-arquivos --member=serviceAccount:$SA --role=roles/storage.objectAdmin

CONN=$PROJECT:$REGION:flash-db
printf '%s' "postgresql+psycopg://flash_app:SENHA_FORTE_DO_APP@/flash_inova?host=/cloudsql/$CONN" | gcloud secrets create database-url --data-file=-
printf '%s' "postgresql+psycopg://flash_owner:SENHA_DO_DONO@/flash_inova?host=/cloudsql/$CONN" | gcloud secrets create migrations-database-url --data-file=-
openssl rand -base64 48 | tr -d '\n' | gcloud secrets create secret-key --data-file=-
printf '%s' "SENHA_SMTP_DO_SES" | gcloud secrets create smtp-password --data-file=-
for s in database-url migrations-database-url secret-key smtp-password; do
  gcloud secrets add-iam-policy-binding $s --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
done
```

## 4. Imagem

Na raiz do repositório:

```bash
gcloud artifacts repositories create flash --repository-format=docker --location=$REGION
IMAGE=$REGION-docker.pkg.dev/$PROJECT/flash/app:$(git rev-parse --short HEAD)
gcloud builds submit --tag $IMAGE .
```

## 5. Migrações e primeiro Consultor (Cloud Run Jobs)

```bash
COMMON="--image=$IMAGE --region=$REGION --service-account=$SA --set-cloudsql-instances=$CONN"
gcloud run jobs create migrar $COMMON --command=alembic --args=upgrade,head \
  --set-secrets=MIGRATIONS_DATABASE_URL=migrations-database-url:latest --set-env-vars=APP_DB_ROLE=flash_app
gcloud run jobs execute migrar --region=$REGION --wait

read -s -p "Senha do Consultor: " SENHA; printf '%s' "$SENHA" | gcloud secrets create consultor-senha --data-file=-; unset SENHA
gcloud secrets add-iam-policy-binding consultor-senha --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
gcloud run jobs create criar-consultor $COMMON --command=python \
  --args=-m,app.cli,criar-consultor,--nome,"Seu Nome",--email,voce@flashresponse.com.br \
  --set-secrets=DATABASE_URL=database-url:latest,SECRET_KEY=secret-key:latest,CONSULTOR_SENHA=consultor-senha:latest \
  --set-env-vars=BASE_DOMAIN=$DOMAIN
gcloud run jobs execute criar-consultor --region=$REGION --wait
gcloud run jobs delete criar-consultor --region=$REGION --quiet && gcloud secrets delete consultor-senha --quiet
```

A cada nova versão: `gcloud builds submit`, `gcloud run jobs update migrar --image=$IMAGE`, executar `migrar` e depois atualizar o serviço (passo 6).

## 6. Serviço (Cloud Run)

```bash
gcloud run deploy flash-inova --image=$IMAGE --region=$REGION --service-account=$SA \
  --add-cloudsql-instances=$CONN --ingress=internal-and-cloud-load-balancing --allow-unauthenticated \
  --min-instances=0 --max-instances=4 --memory=512Mi \
  --set-secrets=DATABASE_URL=database-url:latest,SECRET_KEY=secret-key:latest,SMTP_PASSWORD=smtp-password:latest \
  --set-env-vars=BASE_DOMAIN=$DOMAIN,APP_DB_ROLE=flash_app,STORAGE_BACKEND=gcs,GCS_BUCKET=$PROJECT-arquivos,EMAIL_BACKEND=smtp,SMTP_HOST=email-smtp.sa-east-1.amazonaws.com,SMTP_USER=USUARIO_SMTP_DO_SES,EMAIL_FROM=nao-responda@$DOMAIN
```

Para a primeira votação ao vivo num evento, use `--min-instances=1` no dia (evita a espera da primeira abertura).

## 7. Endereço e HTTPS (subdomínio por cliente)

O Cloud Run sozinho não aceita subdomínio curinga, por isso entra um Load Balancer com certificado `*.inova...`.

```bash
gcloud compute addresses create flash-ip --global
gcloud compute addresses describe flash-ip --global --format='value(address)'     # IP para o DNS

gcloud certificate-manager dns-authorizations create flash-dns --domain=$DOMAIN
gcloud certificate-manager dns-authorizations describe flash-dns                  # CNAME para o DNS
gcloud certificate-manager certificates create flash-cert --domains="$DOMAIN,*.$DOMAIN" --dns-authorizations=flash-dns
gcloud certificate-manager maps create flash-map
gcloud certificate-manager maps entries create flash-raiz --map=flash-map --certificates=flash-cert --hostname=$DOMAIN
gcloud certificate-manager maps entries create flash-curinga --map=flash-map --certificates=flash-cert --hostname="*.$DOMAIN"

gcloud compute network-endpoint-groups create flash-neg --region=$REGION --network-endpoint-type=serverless --cloud-run-service=flash-inova
gcloud compute backend-services create flash-backend --global --load-balancing-scheme=EXTERNAL_MANAGED
gcloud compute backend-services add-backend flash-backend --global --network-endpoint-group=flash-neg --network-endpoint-group-region=$REGION
gcloud compute url-maps create flash-lb --default-service=flash-backend
gcloud compute target-https-proxies create flash-https --url-map=flash-lb --certificate-map=flash-map
gcloud compute forwarding-rules create flash-https --global --load-balancing-scheme=EXTERNAL_MANAGED \
  --address=flash-ip --target-https-proxy=flash-https --ports=443
```

**No painel de DNS do flashresponse.com.br** (onde o domínio está hoje), crie:

| Tipo | Nome | Valor |
|---|---|---|
| A | `inova` | IP do `flash-ip` |
| A | `*.inova` | IP do `flash-ip` |
| CNAME | o nome que o `dns-authorizations describe` mostrar | o valor que ele mostrar |

O certificado fica ativo em até uma hora depois do DNS. O site atual do flashresponse.com.br não muda.

## 8. E-mail (Amazon SES, São Paulo)

1. Na AWS, região **sa-east-1**, abra o SES e verifique o domínio `inova.flashresponse.com.br` (Easy DKIM).
2. Crie no DNS os 3 CNAMEs de DKIM que o SES mostrar, mais um TXT SPF em `inova`: `v=spf1 include:amazonses.com ~all`
   e um TXT DMARC em `_dmarc.inova`: `v=DMARC1; p=none; rua=mailto:voce@flashresponse.com.br`.
3. Peça a saída do sandbox (Request production access), explicando que são e-mails transacionais (ativação de conta, senha, código de votação).
4. Em SMTP settings, crie as credenciais SMTP: o usuário vai em `SMTP_USER`, a senha no segredo `smtp-password`.

## 9. Backup e restauração

- O Cloud SQL faz backup diário (guardado 30 dias) e permite voltar a qualquer minuto dos últimos 7 dias.
- **Antes do primeiro cliente, teste a restauração** numa instância nova:
  `gcloud sql backups list --instance=flash-db` e
  `gcloud sql backups restore ID_DO_BACKUP --restore-instance=flash-db-teste --backup-instance=flash-db`
  (crie `flash-db-teste` antes e apague depois).
- Arquivos: ative o versionamento do bucket para recuperar algo apagado por engano:
  `gcloud storage buckets update gs://$PROJECT-arquivos --versioning`

## 10. Monitoramento

- Erros e logs: Cloud Run › flash-inova › Logs (falhas de e-mail aparecem como "Falha ao enviar e-mail").
- App fora do ar: crie uma verificação de disponibilidade em Monitoring › Uptime checks para
  `https://inova.flashresponse.com.br/api/health`, com alerta por e-mail.
- Orçamento: Faturamento › Orçamentos e alertas, com alerta em 50%, 90% e 100% do valor mensal combinado.
