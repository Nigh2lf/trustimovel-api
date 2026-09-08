# CLAUDE.md

## Objetivo

Este projeto utiliza Django e Django REST Framework, e serve dois painéis web feitos em Vite + React + TypeScript: o da imobiliária (`trustimovel-vite`) e o administrativo (`trustimovel-vite-admin`). Ver "Frentes do sistema".

Ao desenvolver ou modificar funcionalidades, siga uma abordagem:

* simples;
* organizada;
* previsível;
* fácil de manter;
* alinhada aos padrões já existentes no projeto.

Priorize sempre a solução mais simples que resolva corretamente o problema.

Não crie abstrações, camadas ou estruturas adicionais sem necessidade real.

> O `README.md` desta pasta está desatualizado: descreve um "boilerplate com apenas o model `User`".
> O projeto hoje tem cerca de 30 models. Use este arquivo como referência.

---

## Arquitetura, fluxo e funções

Esta seção descreve **o que o sistema é**. O restante do documento descreve **como escrever código
nele** — leia as duas partes antes de mexer.

### O que a API serve

Um SaaS multi-inquilino para imobiliárias. A API é a única dona do banco e das regras de negócio;
os dois painéis React são clientes dela. Visão geral dos três projetos em [../CLAUDE.md](../CLAUDE.md).

```
Plan  ──┐
        └─→ Agency ──→ User (type = ADMIN | USER | BROKER; o corretor guarda presença e ordem na fila)
                   ├──→ Property ──→ PropertyPhoto / PropertyPrice / PropertyFee / PropertyExporter
                   │              └──→ PropertyHistory              (trilha de alterações)
                   ├──→ Condominium ──→ CondominiumPhoto
                   ├──→ Broker, Owner, Client
                   ├──→ Lead ──→ LeadInteraction        (CRM; a fila de atendimento vive em campos do Lead
                   │                                    e nos eventos da LeadInteraction, sem tabela própria)
                   ├──→ ServiceTicket ──→ ServiceTicketMessage
                   ├──→ Task, Deal                      (tarefas e funil; FK opcional p/ Lead)
                   ├──→ AgencySettings                 (configurações do painel + regras da fila)
                   ├──→ BlogPost ──→ BlogCategory
                   ├──→ SiteBanner, CompanySection
                   └──→ AgencyExporter ──→ AgencyExporterPlan

Catálogos globais (não pertencem a nenhuma Agency):
   Country → State → City → Neighborhood
   PropertyType, Feature, Fee, Exporter → ExporterPlan
```

`Agency` é o inquilino. Quase todo model de negócio tem FK para ela, e é isso que separa os dados
de uma imobiliária dos da outra.

### Mapa dos arquivos

```text
config/
├── settings.py           JWT, MySQL, S3 opcional, DRF (paginação 15, filtros)
├── urls.py               ★ os dois routers + login + dashboard + swagger
└── storage.py            MediaStorage do S3
core/                     app da imobiliária — o produto
├── models.py             todos os models do sistema (~870 linhas)
├── filters.py            FilterSets do django-filter
├── classes/
│   ├── base_viewset.py   ★ BaseViewSet: envelope, transação, soft delete
│   ├── permission_type_user.py   AdminPermissionClass, UserPermissionClass, AllPermissionClass
│   └── envelope.py       success_response / error_response do envelope novo
├── views/
│   ├── auth.py           ViewTokenObtainPair (login com throttle)
│   ├── property.py       ★ GlobalCatalogViewSet, AgencyScopedViewSet + imóvel, pessoas, fotos
│   ├── crm.py            leads (+interactions/convert), service-tickets (+messages), tasks, deals
│   ├── blog.py, site.py  herdam de AgencyScopedViewSet
│   ├── user.py           UserViewSet + profile / forgot-password
│   ├── dashboard.py      números da tela inicial (imóveis + bloco crm)
│   ├── reports.py        agregados da tela de Relatórios, por período
│   ├── queue.py          fila de atendimento: estado (GET) + actions; o relógio roda a cada leitura
│   └── address.py        busca de CEP
├── serializers/          authentication, property (943 linhas), blog, site, user, crm, queue
├── services/             address (CEP), photos (resize/thumbnail), property_history, queue (roleta, prazos, transições), services_emails
├── management/commands/  createuser, queuetick (relógio da fila, para o cron) + os seeds
└── template_emails/
admin_web/                app do painel da plataforma — 170 linhas, tudo aqui exige ADMIN
├── views.py              AdminViewSet + um ViewSet por cadastro global
├── serializers.py
└── urls.py
```

### Rotas de topo (`config/urls.py`)

| Prefixo | Serve | Quem acessa |
| --- | --- | --- |
| `/` | Router do painel da imobiliária: `properties`, `clients`, `owners`, `brokers`, `condominiums`, `leads`, `service-tickets`, `tasks`, `deals`, `blog-posts`, `site-banners`, `exporters`, `countries`…`neighborhoods` | Usuário autenticado, escopo da própria `agency` |
| `/admin-web/` | Router do painel da plataforma: `agencies`, `plans`, `users`, catálogos globais | **Só `ADMIN`** |
| `/auth-user/` | Login, devolve `access` + `refresh` | Público |
| `/token-refresh/` | Renova o access | Público |
| `/dashboard/` | Números do painel inicial | Autenticado |
| `/properties/{id}/history/` | Histórico de alterações do imóvel | Autenticado, recurso `imoveis` (leitura) |
| `/reports/` | Agregados da tela de Relatórios, filtrados por período | Autenticado, recurso `relatorios` |
| `/queue/` | Fila de atendimento: estado (`GET`), regras (`settings/`), ações por lead (`leads/{id}/accept`, `decline`, `notes`, `close`, `assign`, `return`) e por corretor (`brokers/{id}/presence`, `move`, `toggle`) | Autenticado, recurso `fila`; o corretor (`BROKER`) só mexe no que está com ele |
| `/addresses/lookup/` | Busca de endereço por CEP | Autenticado |
| `/admin/` | Django Admin | Staff |
| `/swagger/`, `/redoc/` | Documentação da API | Público |

### As quatro classes-base que definem o comportamento

Praticamente todo endpoint herda de uma delas. **Entender as quatro é entender a API inteira.**

**1. `BaseViewSet`** (`core/classes/base_viewset.py`) — a base de tudo:

- Envelopa toda resposta em `{success, status, message, data, error}`.
- `create`, `update` e `destroy` rodam dentro de `@transaction.atomic`.
- `perform_destroy` faz **soft delete**: chama `instance.delete(deleted_by=request.user)`, que só
  preenche `deleted_at`. O registro nunca sai do banco.
- O `dispatch` captura exceções e **converte todo 403 em 401**. Os painéis interpretam 401 como
  sessão morta e derrubam o usuário para o login — logo, falta de permissão e token expirado são
  indistinguíveis no cliente.
- Erro inesperado vira 500 com mensagem genérica; o traceback vai para o log, não para a resposta.

**2. `AgencyScopedViewSet`** (`core/views/property.py`) — o isolamento entre inquilinos:

```python
def get_queryset(self):
    return self.model.objects.filter(
        agency_id=self.request.user.agency_id,
        deleted_at__isnull=True,
    )

def perform_create(self, serializer):
    serializer.save(agency_id=self.request.user.agency_id)
```

É a peça de segurança mais importante do projeto. O usuário **nunca informa** a qual imobiliária o
registro pertence — isso sai do token. Um `get_queryset` que sobrescreva isso sem chamar `super()`
abre vazamento de dados entre imobiliárias.

**3. `GlobalCatalogViewSet`** (`core/views/property.py`) — catálogo compartilhado:
qualquer autenticado **lê** (`list`, `retrieve`); só `ADMIN` **escreve**. É como países, estados,
cidades, tipos de imóvel, infraestruturas e taxas ficam iguais para todo mundo.

**4. `AdminViewSet`** (`admin_web/views.py`) — `permission_classes = [IsAuthenticated,
AdminPermissionClass]`. Todo o app `admin_web` passa por aqui: nenhum usuário comum entra.

### Convenções do banco

- **PK é `UUIDField`**, `default=uuid.uuid4`, `editable=False`. Não existe id sequencial.
- **Soft delete em todo lugar**: `delete()` é sobrescrito para preencher `deleted_at` (e `is_active`
  em `User` e `Property`). Consulta sem `deleted_at__isnull=True` traz lixo apagado.
- `created_at` / `updated_at` automáticos em todos os models.
- `on_delete=PROTECT` para catálogos e referências que não podem sumir; `CASCADE` para o que pertence
  à `Agency` ou ao `Property`.
- `Photo` é model abstrato-base concretizado em `PropertyPhoto` e `CondominiumPhoto`.

### Permissionamento por recurso

Dentro da imobiliária, o acesso é governado por um nível progressivo em cada tela do menu.
O catálogo de recursos e a escada de níveis estão em [core/resources.py](core/resources.py);
as concessões, na tabela `UserPermission`.

| Nível | Valor | Libera |
| --- | --- | --- |
| Sem acesso | 0 | nada — menu escondido e endpoint em 403 |
| Leitura | 1 | `list`, `retrieve` |
| Leitura e escrita | 2 | `create`, `update`, `partial_update` |
| Total | 3 | `destroy` |

O valor é **ordinal de propósito**: a checagem inteira é `nivel >= exigido`, sem tabela de
verdade. `User.level_for(resource)` resolve o nível (com cache por instância) e
`User.can(resource, level)` é o predicado usado em todo lugar.

Quem aplica é o `ResourcePermission`
([core/classes/permission_resource.py](core/classes/permission_resource.py)), presente no
`AgencyScopedViewSet`, no `PhotoViewSet`, no `UserViewSet`, no `DashboardView` e no `ReportsView`. Cada um
declara `resource = '...'`. Regras que valem a pena conhecer antes de mexer:

- **ViewSet sem `resource` nega o acesso.** Endpoint novo que esqueça de declarar aparece
  como erro visível, não como buraco aberto.
- **`@action` customizada declara o nível dela** com `@requires_level(AccessLevel.FULL)`.
  Sem declaração, é tratada como escrita — o palpite conservador para um POST extra.
- **`APIView` simples** (sem `action`) cai no mapa por método HTTP.
- **Catálogos globais não têm recurso.** `PropertyType`, `Feature`, `Fee`, `Exporter`,
  país/estado/cidade/bairro seguem no `GlobalCatalogViewSet`: qualquer autenticado lê, só
  ADMIN escreve. São dado de referência que o formulário de imóvel consome — amarrá-los a
  um recurso quebraria o combobox de quem não tem aquela tela.
- **`type=ADMIN` passa por cima de tudo**, sem precisar de linha gravada.

Duas travas impedem a imobiliária de se trancar para fora, já que administrar usuários é
apenas o recurso `usuarios` e não um papel separado: ninguém reduz a própria permissão em
Usuários, e ninguém rebaixa ou exclui o último usuário com Total nele. O primeiro usuário
de uma conta nasce com acesso a tudo (`grant_full_access`, chamado pelo `admin_web`).

Testes em [core/tests_permissions.py](core/tests_permissions.py).

### Fluxo de autenticação

```
POST /auth-user/ {email, password}
  └─ ViewTokenObtainPair (LoginSerializer, throttle_scope="login")
       ├─ credencial inválida → 401 com mensagem em português
       └─ ok → {access, refresh, user}

requisições seguintes: Authorization: Bearer <access>
  └─ JWTAuthentication → request.user
       └─ AllPermission / AdminPermission / UserPermission conforme o ViewSet
            └─ get_queryset filtra por request.user.agency_id
```

Access vale **180 minutos** (`SIMPLE_JWT.ACCESS_TOKEN_LIFETIME`). O login tem throttle por escopo;
o `UserViewSet` expõe ainda `profile`, `permission-resources`, `forgot-password` e
`change-password-forgot-password`.

**401 e 403 são coisas diferentes e precisam continuar assim.** 401 é sessão inválida, e os
painéis reagem limpando o `localStorage` e mandando para o login. 403 é usuário autenticado
sem permissão, e a tela só avisa. O `BaseViewSet` já converteu todo 403 em 401 — com o
permissionamento no ar isso expulsaria da aplicação quem apenas esbarrasse numa permissão.

### Histórico do imóvel

Toda alteração feita pelo painel deixa rastro em `PropertyHistory`, que a listagem de imóveis
mostra no botão *Histórico de alterações*.

```
PATCH /properties/{id}/
  └─ PropertyViewSet.perform_update
       ├─ snapshot(instance)          retrato antes de salvar, já com valores legíveis
       ├─ super().perform_update()
       └─ record_update(...)          diff dos rótulos → uma linha com {label, from, to}

POST/DELETE /property-photos/
  └─ PhotoViewSet.log_photo_action    gancho vazio na base; só PropertyPhotoViewSet grava
```

O serviço é [core/services/property_history.py](core/services/property_history.py). Duas coisas
para saber antes de mexer: o retrato **precisa** sair antes do `save`, senão os valores antigos
já se perderam; e o diff guarda o rótulo da tela e o valor legível, não o nome do campo nem o
UUID da relação — o histórico é lido pelo corretor. Edição que não muda nada não vira linha.

Campo novo no imóvel que deva entrar no histórico precisa ser declarado em `TRACKED_FIELDS`.

### Fluxo de fotos

Upload em `/property-photos/` (ou `/condominium-photos/`), tratado por `core/services/photos.py`:

```
arquivo recebido
  → resize_upload()      reduz pelo maior lado e regrava no formato de PROPERTY_PHOTO_FORMAT
  → build_thumbnail()    grava a miniatura ao lado, como mini-<nome>
  → gravação em S3 (se configurado) ou em media/
exclusão
  → delete_thumbnail() + promote_next_main()   se a capa saiu, a próxima foto assume
```

O `PhotoViewSet` tem paginação própria e uma action `POST /…/delete-all/`. A ordem das fotos vem do
painel, que arrasta e envia a nova posição.

### Armazenamento

`config/settings.py` decide sozinho: se `AWS_STORAGE_BUCKET_NAME`, `AWS_ACCESS_KEY_ID` e
`AWS_SECRET_ACCESS_KEY` estiverem preenchidos (e não forem os placeholders), usa
`config.storage.MediaStorage` no S3 (`STORAGES['default']`). Senão, cai para `media/` local. Não
há flag manual. Static fica sempre local, em qualquer um dos casos.

Com S3 ligado:

- `AWS_S3_REGION_NAME` precisa ser a região do bucket (o de produção, `trustimovel-api-files`,
  está em `us-east-1`). Região errada dá 400 no upload e URL que não abre.
- As URLs das fotos não são assinadas: `https://<bucket>.s3.<região>.amazonaws.com/media/...`
  (ou `AWS_S3_CUSTOM_DOMAIN`, se definido). O bucket precisa de uma policy liberando
  `s3:GetObject` em `media/*`; sem ela o upload grava, mas a foto responde 403.
- O bucket usa "Object Ownership: bucket owner enforced", então nada de ACL por objeto
  (`AWS_DEFAULT_ACL = None`).
- Os testes que gravam arquivo forçam `FileSystemStorage` (`LOCAL_FILE_STORAGES`), então rodar a
  suíte com `AWS_*` no `.env` não escreve no bucket.

### Comandos de dados

`core/management/commands/`:

| Comando | Para que serve |
| --- | --- |
| `createuser` | Cria usuário interativamente (`--email`, `--password`, `--no-input`, `--no-validate`) |
| `seedlocations` | Popula países, estados, cidades e bairros (dumps SQL na raiz da pasta de trabalho) |
| `seedcatalogs` | Infraestruturas e taxas |
| `seedpropertytypes` | Tipos de imóvel |
| `seedagencycatalogs` | Catálogos por imobiliária |
| `seedproperties` | Imóveis de exemplo |
| `seedagencydemo` | Volume de demonstração para uma imobiliária: pessoas, imóveis com foto, CRM, blog e banners |
| `queuetick` | Relógio da fila de atendimento: expira ofertas, transfere quem estourou o SLA e redistribui a espera. Para o cron, a cada minuto |
| `syncmedia` | Envia para o S3 os arquivos da pasta `media` local que o banco referencia (fotos, banners e a mini da foto principal), sem mudar registro: o campo guarda só o caminho relativo e a URL vem do storage. `--dry-run` lista, `--orphans` inclui arquivos sem registro |

Tipos de imóvel, infraestruturas e taxas **não têm tela de gerência no painel da imobiliária** — vêm
desses seeds ou do painel administrativo.

`seedagencydemo` é o único que gera volume: aceita `--<cadastro> <n>` para cada bloco, espalha o
histórico pelos últimos meses (`--months`) e desenha fotos de espaço reservado (`--photos 0` pula).
Ele acrescenta um lote a cada execução, nunca substitui o que já existe.

### Ambiente

- Banco: MySQL 8. O compose desta pasta sobe só o banco, com `mysql_native_password` (o
  `mysqlclient` do Windows não fala o `caching_sha2_password` padrão do MySQL 8).
- O compose da pasta de trabalho sobe API + os dois painéis e alcança o banco por
  `host.docker.internal`.
- `.env` é o de fora do Docker; `.env.docker` é montado por cima de `/app/.env` dentro do container
  só para trocar host/porta do banco — o `settings.py` carrega o `.env` com `override=True`.
- **`DEBUG = True`, `ALLOWED_HOSTS = ['*']` e `CORS_ORIGIN_ALLOW_ALL = True` estão fixos no código.**
  Serve para desenvolvimento e precisa mudar antes de publicar.

---

## Princípios gerais

Siga estes princípios em todas as alterações:

1. **KISS — Keep It Simple**

   * Escolha a solução mais simples.
   * Evite código excessivamente genérico.
   * Evite abstrações prematuras.

2. **YAGNI — You Aren't Gonna Need It**

   * Não implemente funcionalidades que não foram solicitadas.
   * Não prepare estruturas para possibilidades futuras sem necessidade atual.

3. **DRY com bom senso**

   * Evite duplicações relevantes.
   * Não crie funções, classes ou serviços apenas para eliminar duas ou três linhas simples repetidas.

4. **Mudanças pequenas**

   * Faça a menor alteração possível para resolver a tarefa.
   * Não refatore partes não relacionadas sem necessidade.
   * Preserve o comportamento existente sempre que possível.

5. **Consistência**

   * Antes de implementar, analise como funcionalidades semelhantes já foram feitas no projeto.
   * Siga os padrões de nomenclatura, organização e estrutura existentes.

---

## Antes de alterar o código

Antes de implementar qualquer mudança:

1. Localize a aplicação Django responsável pela funcionalidade.
2. Leia os models relacionados.
3. Leia os serializers, ViewSets, URLs, permissões e testes existentes.
4. Verifique se já existe alguma função, serviço ou padrão que possa ser reutilizado.
5. Identifique os impactos da mudança.
6. Só então implemente.

Não assuma a estrutura do banco de dados ou o comportamento de uma API sem verificar o código existente.

---

## Organização recomendada

O projeto tem **dois apps Django**, separados por quem consome cada um (ver "Frentes do sistema"):

* `core` — a API do painel da imobiliária, onde vive todo o domínio (models, serviços, imóveis, condomínios);
* `admin_web` — a API do painel administrativo, restrita a usuário `ADMIN`. Não tem models próprios: reutiliza os de `core`.

`core` é organizado com sub-pacotes por responsabilidade. Siga esse padrão ao adicionar código:

```text
core/
├── admin.py
├── apps.py
├── models.py             # todos os models do sistema moram aqui
├── classes/              # BaseViewSet, permissions e outras classes-base
│   ├── base_viewset.py
│   └── permission_type_user.py
├── serializers/
│   ├── __init__.py       # reexporta os serializers públicos
│   └── user.py
├── services/
│   ├── __init__.py
│   └── services_emails.py
├── views/
│   ├── __init__.py
│   └── user.py
├── management/commands/
├── migrations/
└── tests.py

admin_web/                # sem models e sem migrations
├── apps.py
├── serializers.py
├── views.py
├── urls.py
└── tests.py
```

Regras:

* comece com um único arquivo (`serializers.py`, `services.py`, `views.py`) enquanto o conteúdo for pequeno;
* quando o arquivo crescer ou passar a ter responsabilidades distintas, converta-o em pacote (pasta com `__init__.py`), como já feito em `serializers/`, `services/` e `views/`; reexporte os símbolos públicos no `__init__.py`;
* **model novo vai sempre em `core/models.py`**, mesmo quando só o painel administrativo o usa — `admin_web` existe para separar o acesso, não o domínio;
* não crie um terceiro app Django (`python manage.py startapp`) apenas para separar um domínio pequeno; prefira um novo módulo dentro de `core` até que exista um motivo real (público diferente, como foi o caso do `admin_web`) para isolar em outro app;
* não crie `filters.py`, `permissions.py` (fora de `classes/`) etc. antecipadamente — crie apenas quando houver conteúdo real para colocar neles.

---

## Frentes do sistema

O backend serve **dois painéis**, cada um com o seu projeto de frontend:

| Painel | Frontend | Público | API |
| --- | --- | --- | --- |
| Painel da imobiliária | `trustimovel-vite` | usuários `USER`, `BROKER` e `ADMIN` de uma imobiliária | app `core`, na raiz (`/properties/`, `/condominiums/`…) |
| Painel administrativo | `trustimovel-vite-admin` | somente `ADMIN` do sistema | app `admin_web`, sob `/admin-web/` |

Os dois frontends usam a mesma stack (Vite + React + TypeScript + Tailwind + shadcn/ui + TanStack Query) e o mesmo cliente de API (`src/lib/api.ts`), então o formato de resposta precisa ser o mesmo nos dois — ver "Padrão de resposta da API".

### Onde cada endpoint deve nascer

Antes de criar um endpoint, decida quem vai consumi-lo:

* **a imobiliária usa** → `core`, com o queryset filtrado pela imobiliária do usuário (`AgencyScopedViewSet`);
* **só o administrador do sistema usa** (cadastros que valem para todas as imobiliárias: imobiliárias, usuários de qualquer conta, catálogos globais) → `admin_web`;
* **os dois usam com regras diferentes** → o recurso nasce nos dois lugares, cada um com o seu ViewSet e o seu escopo. É o caso de `features`, `fees` e dos catálogos de endereço: em `core` são somente leitura para a imobiliária, em `admin_web` são CRUD completo. Não tente atender aos dois públicos com um ViewSet só e permissões condicionais.

### Regras do app `admin_web`

* todo ViewSet estende `AdminViewSet` (em `admin_web/views.py`), que já aplica `JWTAuthentication` + `IsAuthenticated` + `AdminPermissionClass`. **Nunca** declare `permission_classes` mais fracas em um recurso do painel administrativo;
* reutilize os serializers de `core` quando servirem; crie um serializer em `admin_web/serializers.py` apenas quando o administrador precisar de campos que a imobiliária não pode ver ou gravar (é o caso de `AdminUserSerializer`, que deixa `agency` e `type` editáveis, e dos serializers que acrescentam rótulos de relação para a listagem);
* `admin_web` não tem `models.py` nem `migrations/`;
* toda rota nova entra no router de `admin_web/urls.py`, que já está incluído sob `/admin-web/` em `config/urls.py`;
* todo recurso novo precisa entrar na lista `ENDPOINTS` de `admin_web/tests.py`, que verifica de uma vez o acesso sem token, o de usuário comum e o de administrador.

### Regras do frontend administrativo

O `trustimovel-vite-admin` é **dirigido por configuração**: `src/lib/resources.ts` descreve cada cadastro (rota, endpoint, colunas da listagem e campos do formulário) e as telas genéricas `ResourceList`/`ResourceForm` fazem o resto, junto do menu lateral.

Para expor um cadastro novo do `admin_web`, acrescente um item em `ADMIN_RESOURCES` — não crie uma tela por cadastro. Só escreva uma tela dedicada quando o cadastro tiver regra que a tela genérica não cobre (etapas, upload, campos aninhados).

---

## Models

Os models devem representar dados e regras diretamente relacionadas à entidade.

Boas práticas:

* utilizar nomes claros;
* definir `related_name` explícito quando útil;
* utilizar `choices` para valores limitados, sempre com o valor armazenado em MAIÚSCULO (ver "Nomenclatura");
* adicionar índices apenas quando houver necessidade;
* definir constraints no banco para regras importantes;
* utilizar `__str__`;
* evitar lógica extensa dentro do model;
* evitar chamadas externas, envio de mensagens ou processamento pesado em `save()`.

Exemplo:

```python
import uuid

from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendente"
        PAID = "PAID", "Pago"
        CANCELLED = "CANCELLED", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Order #{self.pk}"
```

### Chave primária

Toda tabela usa **UUID** como chave primária, nunca `AutoField`/`BigAutoField` incremental — inclusive `User`, que já segue esse padrão.

```python
import uuid
from django.db import models


class MyModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ...
```

Não crie um campo `uid`/`external_id` separado como identificador público — o próprio `id` já é UUID, então ele é o identificador. Isso também evita enumeração sequencial de recursos (ver "Pentest").

### Soft delete

O projeto usa soft delete como padrão de exclusão (ver `core/models.py`, model `User`): em vez de remover a linha do banco, o model sobrescreve `delete()` para marcar `deleted_at` / `is_active` (e, quando fizer sentido, `deleted_by`) e salvar. Novos models que precisem de exclusão reversível devem seguir esse mesmo padrão em vez de inventar uma abordagem diferente.

Sempre que alterar um model, avalie a necessidade de criar uma migration.

Não edite migrations antigas que já possam ter sido aplicadas em outros ambientes.

---

## Serializers

Os serializers devem ser responsáveis por:

* serialização dos dados;
* validação de entrada;
* conversão de valores;
* representação da resposta;
* criação ou atualização simples de objetos.

Prefira `ModelSerializer` quando estiver trabalhando diretamente com models.

Exemplo:

```python
from rest_framework import serializers

from .models import Order


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = [
            "id",
            "customer",
            "status",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]
```

### Validações

Utilize validações de campo para regras isoladas:

```python
def validate_name(self, value: str) -> str:
    value = value.strip()

    if len(value) < 3:
        raise serializers.ValidationError(
            "O nome deve possuir pelo menos 3 caracteres."
        )

    return value
```

Utilize `validate()` para regras que envolvam mais de um campo:

```python
def validate(self, attrs):
    start_date = attrs.get("start_date")
    end_date = attrs.get("end_date")

    if start_date and end_date and end_date < start_date:
        raise serializers.ValidationError(
            {"end_date": "A data final não pode ser anterior à data inicial."}
        )

    return attrs
```

Evite:

* consultas repetidas ao banco;
* processamento pesado;
* chamadas para APIs externas;
* regras de negócio extensas dentro do serializer;
* serializers com responsabilidades não relacionadas.

---

## ViewSets

Utilize ViewSets do Django REST Framework seguindo estas regras.

O projeto já possui `core.classes.base_viewset.BaseViewSet` (um `ModelViewSet` com resposta padronizada e transações atômicas em `create`/`update`/`destroy`). Novos ViewSets com CRUD devem estender `BaseViewSet` em vez de `ModelViewSet` diretamente, para manter esse comportamento consistente — ver "Padrão de resposta da API". Models com soft delete (ver "Soft delete") devem sobrescrever `delete()` no model, não `perform_destroy()` no ViewSet.

### Escolha da classe

Utilize `ModelViewSet` quando o recurso possuir CRUD completo:

```python
from rest_framework.viewsets import ModelViewSet

from .models import Order
from .serializers import OrderSerializer


class OrderViewSet(ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
```

Utilize `ReadOnlyModelViewSet` quando o recurso permitir apenas leitura:

```python
from rest_framework.viewsets import ReadOnlyModelViewSet


class OrderViewSet(ReadOnlyModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
```

Quando apenas algumas operações forem necessárias, utilize mixins:

```python
from rest_framework import mixins
from rest_framework.viewsets import GenericViewSet


class OrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet,
):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
```

Não exponha métodos HTTP que não sejam necessários.

---

## ViewSets devem ser simples

O ViewSet deve controlar principalmente:

* queryset;
* serializer;
* permissões;
* filtros;
* paginação;
* ações HTTP;
* chamada de serviços quando houver lógica de negócio relevante.

Evite colocar lógica de negócio extensa diretamente no ViewSet.

Prefira não sobrescrever métodos como:

* `list`;
* `retrieve`;
* `create`;
* `update`;
* `partial_update`;
* `destroy`.

Primeiro verifique se o comportamento pode ser resolvido com:

* `get_queryset`;
* `get_serializer_class`;
* `get_permissions`;
* `perform_create`;
* `perform_update`;
* filtros;
* serializers;
* services;
* permissions.

---

## Querysets

Sempre defina o queryset de forma clara.

Exemplo:

```python
class OrderViewSet(ModelViewSet):
    queryset = Order.objects.all().order_by("-created_at")
    serializer_class = OrderSerializer
```

Quando o queryset depender do usuário:

```python
def get_queryset(self):
    return (
        Order.objects
        .filter(customer=self.request.user)
        .order_by("-created_at")
    )
```

Não retorne dados pertencentes a outros usuários ou empresas.

Em sistemas multiempresa, aplique o filtro da empresa em todas as consultas relevantes.

Em models com soft delete (ver "Soft delete"), filtre `deleted_at__isnull=True` (como em `UserViewSet.get_queryset`) para não retornar registros excluídos.

### Otimização

Utilize `select_related` para relacionamentos diretos:

```python
queryset = (
    Order.objects
    .select_related("customer")
    .order_by("-created_at")
)
```

Utilize `prefetch_related` para relacionamentos reversos ou muitos-para-muitos:

```python
queryset = (
    Order.objects
    .select_related("customer")
    .prefetch_related("items")
    .order_by("-created_at")
)
```

Não adicione otimizações sem entender quais relacionamentos são utilizados pelo serializer.

Evite consultas ao banco dentro de loops.

---

## Serializers diferentes por ação

Utilize `get_serializer_class()` somente quando as ações realmente precisarem de estruturas diferentes.

```python
def get_serializer_class(self):
    if self.action == "create":
        return OrderCreateSerializer

    if self.action == "retrieve":
        return OrderDetailSerializer

    return OrderSerializer
```

Não crie serializers separados quando um único serializer simples atender corretamente às operações.

---

## Permissões

Defina permissões explicitamente.

```python
from rest_framework.permissions import IsAuthenticated


class OrderViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
```

Para permissões específicas, siga o padrão já usado no projeto em `core/classes/permission_type_user.py` (`AllPermissionClass`, `AdminPermissionClass`, `UserPermissionClass`, baseadas em `User.type`).

Exemplo:

```python
from rest_framework.permissions import BasePermission


class CanManageOrder(BasePermission):
    message = "Você não possui permissão para gerenciar este pedido."

    def has_object_permission(self, request, view, obj):
        return obj.customer_id == request.user.id
```

Não confie apenas em validações do frontend.

Permissões e isolamento de dados devem ser garantidos no backend.

---

## Filtros

Utilize `django-filter` e os filtros nativos do Django REST Framework sempre que possível.

```python
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter


class OrderViewSet(ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]
    filterset_fields = [
        "status",
        "customer",
    ]
    search_fields = [
        "customer__name",
    ]
    ordering_fields = [
        "created_at",
        "status",
    ]
    ordering = [
        "-created_at",
    ]
```

Para filtros mais complexos, crie uma classe em `filters.py`.

**Todo ViewSet de listagem declara `ordering_fields` explicitamente**, com os campos que as
colunas da tela mostram — os painéis ordenam pelo cabeçalho da coluna e mandam o parâmetro
`ordering` do DRF. Sem a declaração o `OrderingFilter` deduz os campos do serializer, o que
aceita coisas que não deveriam ordenar e recusa relações (`responsible__name`) que a tela usa.
Campo fora da lista é ignorado em silêncio pelo DRF, então a coluna do front precisa usar o
mesmo nome declarado aqui.

A ordenação por preço do imóvel é o único caso que não sai de uma coluna: `PropertyViewSet`
anota `price` com o valor da finalidade filtrada (ou o de venda, quando não há filtro) e usa o
`NullsLastOrderingFilter` para o imóvel sem preço não abrir a lista.

Evite implementar filtros manualmente dentro de `list()`.

---

## Actions

Utilize `@action` apenas para operações relacionadas ao recurso que não sejam CRUD convencional.

Exemplo:

```python
from rest_framework.decorators import action
from rest_framework.response import Response


class OrderViewSet(ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        order.cancel()

        return Response(
            {"detail": "Pedido cancelado com sucesso."}
        )
```

Boas ações:

* cancelar um pedido;
* aprovar uma solicitação;
* reenviar um convite;
* finalizar um processo;
* alterar um status por meio de uma operação específica.

Evite usar `@action` para criar endpoints que poderiam ser recursos próprios.

---

## `perform_create` e `perform_update`

Utilize `perform_create` para atribuições simples relacionadas à requisição:

```python
def perform_create(self, serializer):
    serializer.save(created_by=self.request.user)
```

Utilize `perform_update` para atribuições simples:

```python
def perform_update(self, serializer):
    serializer.save(updated_by=self.request.user)
```

Não coloque fluxos complexos nesses métodos.

Quando houver várias etapas, transações ou integrações, utilize um service.

---

## Services

Crie um service quando existir lógica de negócio relevante, como:

* alteração de múltiplos objetos;
* operação transacional;
* cálculo complexo;
* integração com serviço externo;
* fluxo com várias etapas;
* lógica reutilizada em diferentes pontos.

Não crie services para operações simples de uma linha.

Exemplo:

```python
from django.db import transaction

from .models import Order


@transaction.atomic
def cancel_order(*, order: Order, user) -> Order:
    if order.status == Order.Status.CANCELLED:
        return order

    order.status = Order.Status.CANCELLED
    order.cancelled_by = user
    order.save(
        update_fields=[
            "status",
            "cancelled_by",
        ]
    )

    return order
```

Uso no ViewSet:

```python
from rest_framework.decorators import action
from rest_framework.response import Response

from .services import cancel_order


@action(detail=True, methods=["post"])
def cancel(self, request, pk=None):
    order = self.get_object()

    cancel_order(
        order=order,
        user=request.user,
    )

    serializer = self.get_serializer(order)
    return Response(serializer.data)
```

Prefira argumentos nomeados em services:

```python
cancel_order(
    order=order,
    user=request.user,
)
```

Isso melhora a leitura e reduz erros.

---

## Transações

Utilize `transaction.atomic` quando uma operação precisar alterar vários registros de forma indivisível.

```python
from django.db import transaction


@transaction.atomic
def create_order_with_items(*, customer, items):
    order = Order.objects.create(customer=customer)

    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                product=item["product"],
                quantity=item["quantity"],
            )
            for item in items
        ]
    )

    return order
```

Não envolva toda requisição em transação sem necessidade.

Evite manter uma transação aberta durante chamadas para APIs externas.

---

## Exceções e tratamento de erros

Não utilize `try/except` genérico sem necessidade.

Evite:

```python
try:
    executar_operacao()
except Exception:
    return Response(
        {"detail": "Ocorreu um erro."},
        status=400,
    )
```

Esse padrão:

* esconde erros reais;
* dificulta o diagnóstico;
* pode transformar erro interno em erro de validação;
* prejudica logs e monitoramento.

Capture somente exceções que possam ser tratadas adequadamente.

Exemplo:

```python
try:
    result = gateway.process_payment()
except GatewayUnavailableError as exc:
    raise serializers.ValidationError(
        {"payment": str(exc)}
    ) from exc
```

Deixe erros inesperados serem registrados pelo sistema de monitoramento.

Nunca retorne detalhes internos, stack traces, credenciais ou informações sensíveis na resposta da API.

---

## Respostas HTTP

Utilize os status HTTP adequados:

* `200 OK`: consulta ou atualização concluída;
* `201 Created`: recurso criado;
* `204 No Content`: exclusão ou operação sem corpo de resposta;
* `400 Bad Request`: dados inválidos;
* `401 Unauthorized`: autenticação ausente ou inválida;
* `403 Forbidden`: usuário autenticado sem permissão;
* `404 Not Found`: recurso não encontrado;
* `409 Conflict`: conflito de estado ou duplicidade;
* `500 Internal Server Error`: erro inesperado no servidor.

Prefira o comportamento padrão do Django REST Framework.

Não retorne sempre `200` para operações com erro.

---

## Padrão de resposta da API (envelope)

Toda resposta JSON da API — sucesso ou erro — deve seguir este formato (padrão adotado pelo projeto):

```json
{
  "status": "success",
  "message": "Operação realizada com sucesso",
  "data": {
    "id": "3a1f9c2e-8b4d-4e7a-9c2f-1d6e5b7a9c31",
    "name": "João"
  },
  "errors": []
}
```

Campos:

* `status`: string `"success"` ou `"error"`. Não confundir com o código HTTP, que continua sendo definido normalmente (ver "Respostas HTTP").
* `message`: mensagem curta e legível para humanos sobre o resultado da operação.
* `data`: payload da resposta (objeto, lista ou `null`). Em erros, use `null`.
* `errors`: lista de erros. Vazia (`[]`) em respostas de sucesso. Em erros, cada item deve trazer o máximo de contexto útil, por exemplo `{"field": "email", "message": "Este campo é obrigatório."}`.

Exemplo de erro de validação:

```json
{
  "status": "error",
  "message": "Dados inválidos.",
  "data": null,
  "errors": [
    {"field": "email", "message": "Este campo é obrigatório."}
  ]
}
```

Regras:

* não monte esse dicionário manualmente em cada view; centralize a lógica em um único lugar (um método utilitário compartilhado, um `Renderer` ou o `EXCEPTION_HANDLER` do DRF em `REST_FRAMEWORK`);
* o código HTTP da resposta continua sendo o real (`200`, `201`, `400`, `404` etc.) — o envelope não substitui os status HTTP, apenas padroniza o corpo;
* **estado atual do projeto**: `core/classes/base_viewset.py` (`BaseViewSet._response_format`) hoje retorna um formato diferente (`success` booleano, `status` como código HTTP, `error` no singular). Esse é o formato legado usado pelas views existentes (`UserViewSet` e as demais que estendem `BaseViewSet`). Não misture os dois formatos em endpoints diferentes nem altere esse contrato silenciosamente dentro de uma tarefa não relacionada — migrar `BaseViewSet` (e o consumo no frontend) para o envelope acima deve ser uma tarefa própria e explícita;
* o app `admin_web` também estende `BaseViewSet` e responde no formato legado **de propósito**: os dois frontends compartilham o mesmo `src/lib/api.ts`, e ter dois formatos na mesma API custaria mais do que o ganho. Quando o `BaseViewSet` migrar para o envelope novo, os dois painéis migram juntos;
* para ViewSets/endpoints novos que não dependem do formato legado, siga o envelope acima desde o início.

---

## URLs e routers

Prefira routers do Django REST Framework para ViewSets:

```python
from rest_framework.routers import DefaultRouter

from .views import OrderViewSet


router = DefaultRouter()
router.register(
    "orders",
    OrderViewSet,
    basename="order",
)

urlpatterns = router.urls
```

Utilize nomes de recursos no plural.

Exemplos:

```text
/api/orders/
/api/orders/10/
/api/orders/10/cancel/
```

O projeto tem dois roteadores (ver "Frentes do sistema"): o de `core`, registrado na raiz em `config/urls.py`, e o de `admin_web`, incluído sob o prefixo `/admin-web/`. Um mesmo nome de recurso pode existir nos dois — `/features/` é o catálogo que a imobiliária lê e `/admin-web/features/` é o CRUD do administrador.

Evite verbos em endpoints CRUD.

Evite:

```text
/api/create-order/
/api/list-orders/
/api/edit-order/10/
```

---

## Paginação

Listagens potencialmente grandes devem utilizar paginação.

Não retorne milhares de registros em uma única resposta sem necessidade explícita.

Respeite a configuração global de paginação do projeto antes de criar uma paginação específica.

---

## Tipagem

Utilize type hints quando melhorarem a leitura.

```python
def calculate_total(*, quantity: int, unit_price: Decimal) -> Decimal:
    return quantity * unit_price
```

Não adicione tipagem excessivamente complexa em código simples.

---

## Nomenclatura

Nomes de **models, campos, arquivos, classes, funções e variáveis são sempre em inglês** — é o único idioma usado no código/schema do projeto, independentemente do domínio (o produto é em português, o código não é).

Português aparece somente em:

* comentários (ver "Comentários");
* texto voltado a humanos: `message` do envelope, erros de validação, `verbose_name`/`help_text`, rótulos (segundo valor) de `choices`;
* conteúdo estático voltado ao usuário final (ex.: templates de e-mail).

O **valor armazenado** de uma `choice` também é inglês e sempre em **MAIÚSCULO** (igual ao nome do membro); só o rótulo exibido é português:

```python
class Status(models.TextChoices):
    PENDING = "PENDING", "Pendente"
    PAID = "PAID", "Pago"
```

Esse é o formato padrão de `choices` do sistema, sem exceção: classe interna herdando de `models.TextChoices` (nunca tupla de tuplas), nome do membro e valor armazenado idênticos e em MAIÚSCULO, rótulo em português. Vale também quando o valor tem mais de uma palavra (`PROPERTY_TAX = "PROPERTY_TAX", "IPTU"`). Referências no projeto: `PropertyPrice.Purpose`, `PropertyFee.FeeType` e `User.Type`.

No campo, aponte para a classe em vez de repetir strings:

```python
status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
```

Ao alterar os valores de um `choices` existente, lembre que o dado já gravado no banco continua com o valor antigo — avalie a necessidade de uma migration de dados.

Utilize nomes descritivos.

Prefira:

```python
order
customer
total_amount
pending_orders
cancel_order
```

Evite:

```python
p
obj
data2
temp
result_final2
function
process
```

Nomes de funções devem indicar claramente a ação executada.

Nomes de variáveis devem indicar claramente o dado armazenado.

---

## Comentários

Comentários devem ser escritos **em português** e ter **no máximo uma linha**.

Regras:

* escreva o comentário sempre em português;
* um comentário ocupa no máximo uma linha — se precisar de mais, simplifique o código ou melhore os nomes em vez de explicar;
* comente apenas quando o código não for autoexplicativo;
* explique o **motivo** (por que), não o **que** o código faz;
* não use blocos de comentário, comentários em várias linhas seguidas nem separadores decorativos (`# ----`, `# ====`);
* não deixe código comentado no repositório — o histórico do Git cumpre esse papel;
* não use `TODO`/`FIXME` como substituto de tarefa; se for necessário, registre em uma linha e abra a tarefa correspondente;
* docstrings só quando realmente agregarem (regra de negócio não óbvia em um service) e também curtas, em português;
* mensagens visíveis na API (erros de validação, `message` do envelope) continuam em português, conforme o padrão do projeto;
* o comentário em si é a única exceção à regra de nomenclatura em inglês (ver "Nomenclatura") — o identificador comentado continua em inglês.

Prefira:

```python
# Evita cobrança duplicada quando o gateway reenvia o webhook.
if Payment.objects.filter(external_id=external_id).exists():
    return
```

Evite comentários longos:

```python
# Aqui verificamos se já existe um pagamento com o mesmo external_id
# no banco de dados, porque o gateway pode reenviar o mesmo webhook
# várias vezes e não queremos cobrar o cliente duas vezes.
if Payment.objects.filter(external_id=external_id).exists():
    return
```

Evite comentários redundantes:

```python
# incrementa o contador
counter += 1
```

---

## Textos para o usuário

Todo texto que aparece na tela ou na resposta da API é escrito **do ponto de vista de quem usa o sistema**, nunca do ponto de vista de quem o desenvolve. Isso vale para títulos, confirmações, mensagens de erro, `message` do envelope, rótulos e e-mails.

Regras:

* fale com o usuário, não sobre ele — quem lê a mensagem é a pessoa que está executando a ação;
* não escreva na primeira pessoa (`eu`, `nós`, "vamos remover", "criamos o registro");
* não descreva o efeito interno ("a foto sai da galeria", "o registro é marcado como excluído"); descreva o que muda para quem está usando;
* em confirmação de ação destrutiva, pergunte de forma direta e diga a consequência prática;
* mantenha o tom neutro e objetivo, sem gíria e sem exclamação desnecessária;
* português correto, com acentuação.

Prefira:

```text
Deseja realmente remover esta foto?
Após remover não será mais possível recuperar a imagem.
```

Evite:

```text
Remover esta foto?
A foto sai da galeria do imóvel e deixa de aparecer para o cliente.
```

---

## Código legado

Ao trabalhar com código existente:

* preserve o padrão atual quando ele for razoável;
* não reescreva arquivos inteiros sem necessidade;
* não altere contratos de API sem solicitação;
* não renomeie campos públicos sem avaliar compatibilidade;
* não remova comportamentos existentes sem verificar o uso;
* mantenha retrocompatibilidade quando necessário.

Quando encontrar um problema fora do escopo, informe-o separadamente em vez de incluí-lo silenciosamente na alteração.

---

## Segurança

Sempre verifique:

* autenticação;
* autorização;
* isolamento por usuário ou empresa;
* validação de entrada;
* exposição de dados sensíveis;
* upload de arquivos;
* injeção de comandos;
* consultas inseguras;
* armazenamento de credenciais.

Nunca coloque no código:

* senhas;
* tokens;
* chaves de API;
* secrets;
* credenciais de banco;
* dados pessoais reais.

Utilize variáveis de ambiente.

Não registre em logs:

* senhas;
* tokens completos;
* dados de cartão;
* documentos pessoais sem necessidade;
* payloads sensíveis.

---

## Pentest

O projeto precisa passar em testes de pentest. Toda alteração deve ser feita assumindo que a API será testada por uma ferramenta automatizada e por um analista, usando como referência o **OWASP API Security Top 10** e o **OWASP Top 10**.

Regra prática: um endpoint só está pronto quando um usuário autenticado comum, um usuário não autenticado e um usuário de outra empresa/conta forem testados contra ele.

### 1. Configuração e deploy

Antes de considerar uma entrega concluída, execute:

```bash
python manage.py check --deploy
```

Nenhum aviso de segurança deve permanecer sem justificativa. Em produção:

```python
DEBUG = False
ALLOWED_HOSTS = ["api.exemplo.com"]        # nunca ["*"]
SECRET_KEY = os.environ["SECRET_KEY"]      # nunca no código

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = ["https://app.exemplo.com"]

X_FRAME_OPTIONS = "DENY"
```

Outras regras:

* `DEBUG = True` em produção é falha crítica — a página de erro do Django expõe settings e trechos de código;
* nunca use `CORS_ALLOW_ALL_ORIGINS = True` em produção; liste as origens explicitamente e só habilite `CORS_ALLOW_CREDENTIALS` quando necessário;
* restrinja ou desabilite `/swagger/` e `/redoc/` em produção (drf-yasg) — documentação pública facilita o mapeamento da API;
* proteja `/admin/` (acesso restrito por rede/VPN ou caminho alterado) ou desabilite se não for usado;
* não exponha `.env`, `.git`, backups, dumps ou arquivos de configuração pelo servidor web.

### 2. Autenticação

* defina `DEFAULT_AUTHENTICATION_CLASSES` e `DEFAULT_PERMISSION_CLASSES` globalmente, com `IsAuthenticated` como padrão — endpoints públicos são a exceção e devem ser explícitos com `AllowAny`;
* tokens de acesso com tempo de vida curto; refresh com rotação e blacklist no logout;
* nunca coloque dados sensíveis dentro do payload do JWT (ele é apenas assinado, não é secreto);
* use os validadores de senha do Django (`AUTH_PASSWORD_VALIDATORS`) e o hash padrão — nunca implemente hash próprio;
* mensagens de login e de recuperação de senha devem ser genéricas, para não permitir enumeração de usuários (não diferencie "usuário não existe" de "senha incorreta");
* tokens de recuperação de senha devem ter validade curta e uso único;
* nunca retorne senha, hash de senha, token de recuperação ou secrets em nenhum serializer.

### 3. Autorização e isolamento de dados (BOLA/IDOR)

É a falha mais comum encontrada em pentest de API. Sempre:

* filtre o queryset pelo usuário/empresa em `get_queryset()` — não confie apenas em `has_object_permission`;
* nunca aceite `user_id`, `empresa_id` ou similar vindo do corpo/query para decidir o dono do registro; use `request.user`;
* verifique permissões também em `@action`, endpoints de download e webhooks;
* prefira retornar `404` (em vez de `403`) para recursos de outro usuário, evitando confirmar a existência do registro;
* revise privilégios por tipo de usuário (`User.type`): um usuário comum não pode escalar para admin por nenhum caminho.

### 4. Entrada de dados

* declare `fields` explicitamente no serializer; não use `fields = "__all__"` em entrada de dados;
* marque como `read_only` todo campo que não deve vir do cliente (`is_active`, `is_staff`, `type`, `created_by`, `deleted_at`, valores calculados) — mass assignment é testado em pentest;
* valide tipo, tamanho e formato de todos os campos; limite o tamanho máximo de strings e de listas;
* não use `raw()`, `extra()`, `RawSQL` nem interpolação de string em consultas; se for inevitável, use parâmetros (`params=[...]`), nunca f-string;
* nunca passe entrada do usuário para `os.system`, `subprocess`, `eval`, `exec` ou `pickle.loads`;
* ao fazer requisição para uma URL informada pelo usuário, valide o destino (protocolo, domínio permitido) para evitar SSRF, e sempre com `timeout`;
* valide também os parâmetros de filtro, ordenação e paginação (`ordering`, `page_size`) — limite o `page_size` máximo.

### 5. Upload de arquivos

* valide extensão, tipo de conteúdo e tamanho máximo;
* não confie no nome enviado pelo cliente; gere um nome próprio e evite caminhos (`../`);
* nunca sirva arquivos enviados pelo usuário a partir de um diretório que possa executar código;
* aplique controle de acesso também no download do arquivo.

### 6. Rate limiting e brute force

Endpoints de autenticação, recuperação de senha e criação de conta precisam de limite de requisições:

```python
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/min",
        "user": "120/min",
        "login": "5/min",
    },
}
```

Use `ScopedRateThrottle` com `throttle_scope = "login"` nas views de autenticação.

### 7. Exposição de informação

* respostas de erro nunca devem conter stack trace, SQL, caminho de arquivo, versão de biblioteca ou dados de outro usuário — use o `EXCEPTION_HANDLER` centralizado (ver "Padrão de resposta da API");
* IDs já são UUID em todas as tabelas (ver "Chave primária" em Models) — isso evita enumeração sequencial de recursos por padrão, não precisa ser avaliado caso a caso;
* não retorne no serializer campos que o consumidor não precisa (e-mail, telefone, documento de terceiros);
* mascare dados sensíveis em log (`****1234`) e nunca registre token completo, senha ou payload de autenticação.

### 8. Dependências

* mantenha Django, DRF e bibliotecas em versões com suporte de segurança;
* antes de fechar uma entrega, verifique vulnerabilidades conhecidas nas dependências (por exemplo `pip-audit` ou `safety`, executados sob demanda; não é necessário adicioná-los ao projeto);
* fixe as versões no arquivo de dependências.

### 9. Testes de segurança obrigatórios

Toda funcionalidade nova precisa de teste para, no mínimo:

* acesso sem autenticação → `401`;
* usuário autenticado sem permissão → `403`;
* acesso a recurso de outro usuário/empresa → `404`;
* campo privilegiado enviado no payload é ignorado.

```python
def test_privileged_field_is_ignored(self):
    self.client.force_authenticate(self.user)

    response = self.client.patch(
        f"/api/users/{self.user.id}/",
        {"type": "admin"},
        format="json",
    )

    self.user.refresh_from_db()
    self.assertNotEqual(self.user.type, "admin")
```

### 10. Checklist antes de concluir

1. `python manage.py check --deploy` sem avisos pendentes.
2. Todo endpoint novo tem `permission_classes` explícito — e, se estiver em `admin_web`, estende `AdminViewSet` e aparece na lista `ENDPOINTS` dos testes.
3. `get_queryset()` isola os dados por usuário/empresa.
4. Nenhum campo sensível é gravável ou retornado indevidamente.
5. Nenhum secret, credencial ou dado real no diff.
6. Erros não vazam detalhes internos.
7. Endpoints sensíveis têm throttle.
8. Testes de autenticação, permissão e isolamento incluídos e passando.

Ao encontrar uma falha de segurança fora do escopo da tarefa, **relate separadamente** em vez de corrigir silenciosamente junto com a alteração.

---

## Performance

Antes de otimizar, identifique o problema real.

Prioridades:

1. evitar consultas dentro de loops;
2. evitar problemas de N+1;
3. utilizar `select_related`;
4. utilizar `prefetch_related`;
5. limitar campos e registros quando necessário;
6. utilizar paginação;
7. utilizar `bulk_create` e `bulk_update` quando apropriado;
8. adicionar índices apenas quando justificado.

Não crie cache sem uma necessidade comprovada.

Não adicione complexidade de infraestrutura para resolver um problema pequeno.

---

## Testes

Toda correção de bug deve, sempre que possível, incluir um teste que reproduza o problema.

Toda funcionalidade importante deve testar:

* cenário de sucesso;
* dados inválidos;
* usuário não autenticado;
* usuário sem permissão;
* isolamento de dados;
* regras de negócio;
* efeitos colaterais importantes.

Exemplo (o projeto usa o Django test runner, via `rest_framework.test.APITestCase`):

```python
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import User


class OrderViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="user@test.com", password="password123")
        self.other_user = User.objects.create_user(email="other@test.com", password="password123")

    def test_user_cannot_view_order_of_another_customer(self):
        order = Order.objects.create(customer=self.other_user)

        self.client.force_authenticate(self.user)

        response = self.client.get(f"/api/orders/{order.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
```

Prefira testes claros e objetivos.

Evite testes que dependam da ordem de execução.

Não utilize serviços externos reais nos testes.

---

## Formatação e qualidade

Antes de concluir uma alteração:

1. Verifique imports não utilizados.
2. Verifique nomes de variáveis e funções (inglês, ver "Nomenclatura").
3. Verifique comentários (português, no máximo uma linha, sem código comentado).
4. Verifique formatação.
5. Execute os testes relacionados.
6. Execute o lint configurado no projeto.
7. Verifique migrations pendentes.
8. Execute o checklist de pentest (ver "Pentest").
9. Confirme que não foram incluídos arquivos sensíveis.
10. Revise o diff completo.
11. Confirme que nenhuma alteração não relacionada foi adicionada.

Hoje o projeto não possui Ruff, Black, isort, mypy ou pytest configurados. Utilize o Django test runner (`python manage.py test`) e `python manage.py check`.

Não introduza uma nova ferramenta (linter, formatter, test runner) sem necessidade real. Se o projeto adicionar alguma dessas ferramentas no futuro, atualize esta seção.

---

## Comandos

Antes de executar comandos, identifique como o projeto é gerenciado.

Pode utilizar:

```bash
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check
python manage.py test              # roda core e admin_web
python manage.py test admin_web    # só o painel administrativo
```

Nos frontends (`trustimovel-vite` e `trustimovel-vite-admin`), as verificações são as mesmas:

```bash
npx tsc --noEmit -p tsconfig.app.json
npx eslint .
npm run build
```

O painel da imobiliária sobe em `localhost:8080` e o administrativo em `localhost:8081`, os dois apontando para a API pela variável `VITE_API_BASE_URL`.

`python manage.py makemigrations` (gerar o arquivo de migration) só deve ser executado quando o usuário pedir explicitamente — não rode automaticamente só porque um model mudou; avise que a migration está pendente.

`python manage.py migrate` **nunca** deve ser executado — nem em dev, nem em teste, nem em produção. Aplicar migrations no banco é decisão do usuário; gere/revise o arquivo de migration e pare por aí.

O projeto possui um comando customizado para criar usuários:

```bash
python manage.py createuser
```

Em ambiente Docker (`docker-compose.yml`), prefira executar os comandos dentro do container em vez de na máquina host.

Não execute operações destrutivas sem necessidade.

Nunca execute (o usuário decide quando/se rodar):

```bash
python manage.py migrate
python manage.py flush
python manage.py migrate app zero
python manage.py reset_db
DROP DATABASE
DROP TABLE
```

---

## Dependências

Antes de instalar uma nova dependência:

1. Verifique se o projeto já possui uma solução equivalente.
2. Avalie se o problema pode ser resolvido com Django, DRF ou biblioteca já instalada.
3. Confirme que a dependência é realmente necessária.
4. Utilize uma biblioteca mantida e conhecida.
5. Verifique se a versão escolhida não possui vulnerabilidade conhecida.
6. Atualize o arquivo de dependências correto.

Não instale uma biblioteca para resolver algo simples que possa ser implementado com poucas linhas claras.

---

## Migrações

Ao alterar models:

1. Crie uma nova migration com `makemigrations` apenas se o usuário pedir explicitamente; caso contrário, avise que há uma migration pendente e pare por aí.
2. Revise o arquivo gerado.
3. Verifique se a migration é segura para os dados existentes.
4. Avalie campos obrigatórios em tabelas que já possuem registros.
5. Evite alterações destrutivas sem estratégia de migração.

Nunca execute `python manage.py migrate` (ver "Comandos") — gerar/revisar o arquivo de migration é o limite da tarefa; aplicá-la no banco é sempre o usuário quem faz.

Para campos novos em tabelas existentes, considere uma implantação em etapas:

1. adicionar o campo como opcional;
2. preencher os dados existentes;
3. tornar o campo obrigatório em uma migration posterior.

---

## Integrações externas

Ao integrar com serviços externos:

* mantenha a integração isolada;
* configure timeout;
* trate exceções conhecidas;
* não registre credenciais;
* considere idempotência;
* valide respostas;
* valide o destino quando a URL vier do usuário (ver "Pentest");
* evite chamadas externas dentro de transações;
* permita testes com mocks ou fakes.

Exemplo:

```python
response = requests.post(
    url,
    json=payload,
    headers=headers,
    timeout=15,
)
response.raise_for_status()
```

Nunca faça chamadas HTTP sem timeout.

---

## Idempotência

Operações que possam ser repetidas devem evitar efeitos duplicados.

Isso é especialmente importante para:

* webhooks;
* pagamentos;
* criação de reservas;
* processamento de filas;
* envio de notificações;
* importações;
* tarefas assíncronas.

Antes de criar um registro, verifique se o evento ou identificador externo já foi processado.

Quando possível, utilize constraints únicas no banco de dados.

---

## Tarefas assíncronas

Utilize tarefas assíncronas apenas para operações que realmente não devam bloquear a requisição, como:

* envio de e-mails;
* processamento pesado;
* geração de arquivos;
* sincronização externa;
* notificações;
* importações demoradas.

Não transforme operações simples em tarefas assíncronas sem necessidade.

As tarefas devem ser:

* idempotentes;
* pequenas;
* rastreáveis;
* tolerantes a repetição;
* seguras em caso de retry.

---

## Documentação das APIs

Quando alterar uma API:

* mantenha nomes consistentes;
* documente novos campos;
* informe campos obrigatórios;
* informe valores possíveis;
* inclua exemplos quando necessário;
* preserve compatibilidade sempre que possível.

O projeto documenta a API com **drf-yasg** (Swagger em `/swagger/`, Redoc em `/redoc/`). Ao alterar uma view ou serializer, confirme que a documentação gerada automaticamente continua refletindo os campos e parâmetros corretos.

A documentação não deve ficar publicamente acessível em produção (ver "Pentest").

---

## Formato esperado das implementações

Ao receber uma tarefa:

1. Explique brevemente o que será alterado.
2. Identifique os arquivos relevantes.
3. Implemente apenas o necessário.
4. Preserve o padrão existente.
5. Adicione ou ajuste testes.
6. Execute as validações disponíveis.
7. Apresente um resumo objetivo das alterações.
8. Informe testes executados e eventuais limitações.

---

## Regras obrigatórias

Sempre:

* escolha a implementação mais simples;
* leia o código existente antes de alterar;
* mantenha ViewSets pequenos;
* utilize serializers para validação;
* utilize services apenas para lógica realmente relevante;
* nomeie models, campos, arquivos, classes, funções e variáveis em inglês;
* escreva comentários em português e com no máximo uma linha;
* coloque o endpoint no app certo: `core` para o painel da imobiliária, `admin_web` para o painel administrativo (ver "Frentes do sistema");
* estenda `AdminViewSet` em todo recurso de `admin_web` e cubra-o nos testes de acesso;
* declare o cadastro novo do administrador em `src/lib/resources.ts` do `trustimovel-vite-admin`, em vez de escrever uma tela por cadastro;
* use UUID como chave primária em toda tabela nova;
* grave os valores de `choices` em inglês e em MAIÚSCULO;
* filtre dados pelo usuário ou empresa quando necessário;
* defina `permission_classes` explicitamente em todo endpoint novo;
* marque como `read_only` campos que não devem vir do cliente;
* evite consultas N+1;
* utilize transações em operações com múltiplas alterações;
* utilize status HTTP corretos;
* siga o envelope de resposta padrão (`status`/`message`/`data`/`errors`) em endpoints novos;
* escreva mensagens de erro claras;
* escreva o texto voltado ao usuário do ponto de vista de quem usa o sistema (ver "Textos para o usuário");
* preserve compatibilidade;
* crie testes para comportamentos importantes, incluindo autenticação, permissão e isolamento de dados;
* execute o checklist de pentest antes de concluir;
* revise o diff antes de concluir.

Nunca:

* crie abstrações desnecessárias;
* nomeie models, campos, arquivos, classes, funções ou variáveis em português;
* escreva comentários com mais de uma linha ou em outro idioma que não português;
* deixe código comentado no repositório;
* coloque toda a lógica dentro do ViewSet;
* sobrescreva métodos do DRF sem necessidade;
* capture `Exception` indiscriminadamente;
* exponha informações sensíveis, stack traces ou detalhes internos na resposta;
* confie em `id` de usuário ou empresa vindo do payload para decidir permissão;
* use `fields = "__all__"` em serializers de entrada;
* monte SQL por interpolação de string;
* faça consultas dentro de loops sem avaliar alternativas;
* misture o envelope de resposta novo com o formato legado do `BaseViewSet` no mesmo endpoint;
* execute `python manage.py migrate` (gerar migration com `makemigrations` só quando solicitado; aplicar no banco é sempre o usuário quem faz — ver "Comandos");
* altere código não relacionado à tarefa;
* instale dependências sem justificativa;
* faça alterações destrutivas sem aviso;
* assuma que uma mudança está correta sem testar;
* implemente funcionalidades que não foram solicitadas.

---

## Regra final

Quando houver mais de uma forma válida de resolver um problema, escolha nesta ordem:

1. recurso nativo do Django ou Django REST Framework;
2. padrão já utilizado no projeto;
3. implementação direta e legível;
4. pequena função reutilizável;
5. service;
6. abstração mais complexa;
7. nova dependência.

A solução ideal é aquela que resolve corretamente o problema com o menor nível de complexidade necessário.
