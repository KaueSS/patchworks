# 🧵 Patch Works e Afins — Versão 2.0

Catálogo online de artesanato sob encomenda (projeto acadêmico).

**Branch principal:** `main` (= **v2.0**)  
**Versão anterior:** branch `v1.0` (SQLite / layout antigo) — preservada no GitHub.

Repositório: https://github.com/gentilneto/patchworks

---

## O que há na v2.0

- Catálogo com busca, categorias e modal de produto  
- Avaliações e página de contato  
- Identidade visual artesanal (UX/UI)  
- Banco **MySQL**  
- Cotação de frete (**Melhor Envio**) no modal  
- Origem do frete editável no **Admin** (CEP + endereço)  
- Validação de CEP (**ViaCEP**)  
- Admin Django  
- Manuais em `docs/`  
- Dados de exemplo em `data/fixture_inicial.json`  
- Mídias em `media/`

---

## Tecnologias

| Camada | Tecnologia |
|--------|------------|
| Backend | Python 3 + Django 6 |
| Banco | MySQL 8 |
| Front | HTML / CSS / JS |
| Frete | Melhor Envio API (sandbox/produção) |
| CEP | ViaCEP |

---

## Branches

| Branch | Conteúdo |
|--------|----------|
| **`main`** | **v2.0 (atual / principal)** |
| `v1.0` | Versão 1.0 original (não apagada) |
| `v2.0` | Espelho da v2 (opcional; use `main`) |

```bash
# Clonar a versão atual (v2)
git clone https://github.com/gentilneto/patchworks.git
cd patchworks

# Se precisar da v1 antiga:
git checkout v1.0
```

---

## Como rodar (equipe)

### Pré-requisitos

- Python 3.12+ (ou 3.14)  
- MySQL 8.x rodando localmente  
- Conta Melhor Envio **Sandbox** (para frete)

### Passos

```bash
git clone https://github.com/gentilneto/patchworks.git
cd patchworks

python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
# source venv/bin/activate

pip install -r requirements.txt

# Configurar ambiente
copy .env.example .env   # Windows
# cp .env.example .env   # Linux/macOS
# Gere uma chave exclusiva para o Django e preencha DJANGO_SECRET_KEY no .env:
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
# Edite .env (chave, MySQL + Melhor Envio). Para executar localmente com imagens,
# use DJANGO_DEBUG=True; não exponha essa configuração em hospedagem pública.
```

### Banco MySQL

1. Crie o banco e o usuário (ajuste senha se quiser):

```sql
CREATE DATABASE IF NOT EXISTS patchworks CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'patchworks'@'localhost' IDENTIFIED BY 'troque-por-uma-senha-local-forte';
GRANT ALL PRIVILEGES ON patchworks.* TO 'patchworks'@'localhost';
FLUSH PRIVILEGES;
```

Use a mesma senha local em `MYSQL_PASSWORD` no `.env`. Não reutilize senhas de outros serviços.

2. Migre e carregue os dados de exemplo:

```bash
python manage.py migrate
python manage.py loaddata data/fixture_inicial.json
python manage.py createsuperuser
```

### Servidor

```bash
python manage.py runserver
```

- Site: http://127.0.0.1:8000/  
- Admin: http://127.0.0.1:8000/admin/

### Melhor Envio (cotação)

1. Cadastre um app em **Integrações → Área Dev.** (sandbox)  
2. Preencha `MELHOR_ENVIO_CLIENT_ID`, `MELHOR_ENVIO_CLIENT_SECRET` e `MELHOR_ENVIO_REDIRECT_URI` no `.env`
3. Callback precisa de **HTTPS** → use o túnel Cloudflare (seção abaixo)  
4. Autorize: http://127.0.0.1:8000/api/melhorenvio/autorizar/  

Para uma apresentação sem credenciais, `MELHOR_ENVIO_SIMULATE_FREIGHT=True` mostra duas opções ilustrativas, identificadas na tela como simulação. Isso não consulta transportadoras nem representa preço ou prazo real. Para testar o Melhor Envio, deixe a opção `False`, configure as credenciais e autorize a conta Sandbox.

Detalhes: `docs/MANUAL_MELHOR_ENVIO.md`

---

## Túnel Cloudflare (HTTPS local) — para o time

O Melhor Envio **não aceita** callback OAuth em `http://127.0.0.1`. O `cloudflared` cria um endereço **HTTPS** temporário que aponta para o Django na sua máquina — **grátis**, sem publicar o site.

```
Internet (HTTPS)  →  Cloudflare  →  seu PC (http://127.0.0.1:8000)
```

### 1. Instalar (uma vez)

```powershell
winget install Cloudflare.cloudflared --accept-package-agreements --accept-source-agreements
```

Feche e abra o PowerShell; confira com `cloudflared --version`.

### 2. Preparar uma demonstração HTTPS

No `.env`, use estes ajustes apenas para a apresentação pelo túnel:

```env
DJANGO_DEBUG=False
DJANGO_TRUST_PROXY_SSL_HEADER=True
DJANGO_SECURE_HSTS_SECONDS=3600
DJANGO_SERVE_MEDIA_FILES=True
MELHOR_ENVIO_SIMULATE_FREIGHT=True
```

O projeto ativa redirecionamento HTTPS e cookies seguros quando `DJANGO_DEBUG=False`. O túnel Cloudflare informa ao Django o protocolo original da visita. O serviço temporário de mídia abaixo mantém as imagens do catálogo disponíveis durante a demonstração. A opção de simulação exibe valores ilustrativos; ela não consulta o Melhor Envio.

### 3. Subir o Django

```powershell
python manage.py runserver --insecure
```

### 4. Abrir o túnel (outro terminal)

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Copie a URL que aparecer, por exemplo:

```
https://nome-aleatorio.trycloudflare.com
```

### 5. Atualizar o `.env` (e o app no Melhor Envio)

```env
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,nome-aleatorio.trycloudflare.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://nome-aleatorio.trycloudflare.com
MELHOR_ENVIO_REDIRECT_URI=https://nome-aleatorio.trycloudflare.com/api/melhorenvio/callback/
```

No Melhor Envio (Área Dev), use o **mesmo** callback. Reinicie o `runserver`.

`runserver --insecure` e `DJANGO_SERVE_MEDIA_FILES=True` servem apenas para uma demonstração curta. Para produção, use um servidor WSGI/ASGI e um serviço próprio para arquivos de mídia; não mantenha `runserver` exposto à internet.

### 6. Fechar o túnel (quando não quiser mais)

1. No terminal do `cloudflared`, pressione **`Ctrl + C`** — o HTTPS some na hora.  
2. (Opcional) Pode fechar também o `runserver` com **`Ctrl + C`**.  
3. A URL `trycloudflare.com` **deixa de funcionar**; na próxima vez que abrir o túnel, a URL **muda** e é preciso atualizar `.env` + callback de novo.

Não precisa “desinstalar” o cloudflared: só pare o processo. O site volta a ser só local em http://127.0.0.1:8000/.

Guia completo: [docs/PASSO_A_PASSO_CLOUDFLARED.md](docs/PASSO_A_PASSO_CLOUDFLARED.md) · conceito: [docs/MANUAL_CLOUDFLARE.md](docs/MANUAL_CLOUDFLARE.md)

---

## Estrutura

```
patchworks/
├── core/                 # App Django (models, views, templates, static, services)
├── patchworks/           # Settings / URLs do projeto
├── media/                # Imagens de produtos e avaliações
├── data/                 # Fixture Django para a equipe
├── docs/                 # Manuais de manutenção
├── .env.example          # Modelo de configuração (copie para .env)
├── requirements.txt
├── breagnote.md          # Pitch do produto
└── manage.py
```

---

## Manuais

| Arquivo | Assunto |
|---------|---------|
| [docs/README.md](docs/README.md) | Índice |
| [docs/MANUAL_MANUTENCAO.md](docs/MANUAL_MANUTENCAO.md) | Manutenção / setup |
| [docs/MANUAL_API.md](docs/MANUAL_API.md) | Rotas e APIs |
| [docs/MANUAL_MELHOR_ENVIO.md](docs/MANUAL_MELHOR_ENVIO.md) | Frete / OAuth |
| [docs/PASSO_A_PASSO_CLOUDFLARED.md](docs/PASSO_A_PASSO_CLOUDFLARED.md) | Túnel HTTPS |
| [docs/MANUAL_CLOUDFLARE.md](docs/MANUAL_CLOUDFLARE.md) | Conceito do túnel |
| [docs/HIGIENIZACAO.md](docs/HIGIENIZACAO.md) | Limpeza do projeto |
| [docs/GUIA_EQUIPE.md](docs/GUIA_EQUIPE.md) | Onboarding dos integrantes |

---

## Segurança (importante para o time)

**Não versionamos** (e não devem ir para o Git):

- `.env` (senhas / tokens reais)  
- `melhorenvio_token.json`  
- `venv/`  

Cada integrante usa o próprio `.env` a partir do `.env.example` e gera o próprio token Melhor Envio.

---

## Bibliografia

1. MENEZES, Nilo. *Introdução à Programação com Python*. 4. ed. Novatec, 2024.  
2. SILBERSCHATZ et al. *Sistemas de Banco de Dados*. 6. ed. Elsevier, 2012.  
3. GAMMA et al. *Padrões de Projeto*. Bookman, 2000.  
4. Django Software Foundation. Documentação oficial — https://docs.djangoproject.com/pt-br/  
5. MDN Web Docs — https://developer.mozilla.org/pt-BR/  
6. Melhor Envio — https://docs.melhorenvio.com.br/  

---

⚠️ Mídias e fixture são para fins acadêmicos e colaboração em equipe.
