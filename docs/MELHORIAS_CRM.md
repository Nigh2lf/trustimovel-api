# Melhorias do CRM — TrustImóvel v3

Levantamento feito em 08/09/2026 sobre o CRM do painel da imobiliária: Leads, Fila de
Atendimento, Atendimentos, Tarefas & Agenda e Funil de Vendas. Cobre a API
([trustimovel-api/](trustimovel-api/)) e o painel ([trustimovel-vite/](trustimovel-vite/)).

O CRM está funcional, integrado à API e coberto por testes (`tests_crm.py`, `tests_queue.py`,
`tests_reports.py`). O que segue são melhorias de produto e de arquitetura, não correções de bug,
salvo onde indicado.

Cada item traz **Hoje** (o que o código faz), **Sugestão** e **Onde mexer**. As marcas
`[impacto alto|médio|baixo]` e `[esforço P|M|G]` são estimativas para priorizar.

---

## Resumo: por onde começar

Maior retorno por esforço, nesta ordem:

1. **Agendar o `queuetick` e avisar a oferta** com som e notificação do navegador (itens 2.2 e 2.4).
2. **Endpoint público de captação** com entrada automática na fila (item 2.1).
3. **Corrigir o relatório de corretores** para considerar `assigned_to` (item 1.3, é bug de dado).
4. **FKs de imóvel e cliente** em lead e negócio (itens 1.1 e 1.2).

---

## 1. Dados e vínculos

### 1.1 Lead não conhece o imóvel `[impacto alto] [esforço M]`

**Hoje.** `Lead` guarda só `property_type` em texto livre
([models.py:987](trustimovel-api/core/models.py#L987)). `Deal`, `Task` e `ServiceTicket`
apontam o imóvel por `property_code`, um `CharField` digitado, sem chave estrangeira. Não há
como responder "quem pediu este imóvel", e o código fica órfão se o imóvel for editado ou excluído.

**Sugestão.** FK opcional `property` para `Property` nos quatro models, mantendo `property_code`
como campo derivado só para exibição durante a transição. No painel, trocar o input de texto por
`RemoteCombobox` apontando para `/properties/`. Com o vínculo no lugar, nascem de graça:
lista de interessados no cartão do imóvel, relatório de procura por imóvel e tarefas de visita
já com endereço.

**Onde mexer.** `core/models.py` + migração; `core/serializers/crm.py`; formulários
`AddLead.tsx`, `AddNegocio.tsx`, `AddTarefa.tsx`, `AddAtendimento.tsx`.

### 1.2 Lead convertido não vira cliente `[impacto alto] [esforço M]`

**Hoje.** A action `convert` em [crm.py](trustimovel-api/core/views/crm.py) cria só o `Deal`,
copiando `client_name` como texto. O cadastro de Pessoas → Clientes fica desconectado do CRM:
não há histórico da pessoa que atravesse lead, negócio e atendimento.

**Sugestão.** Ao converter, criar (ou vincular, se telefone/e-mail já existir) um `Client` e
gravar `Deal.client` como FK. Manter `client_name` só até migrar os registros antigos. A ficha
do cliente passa a mostrar leads, negócios, tarefas e atendimentos da pessoa.

**Onde mexer.** `Deal.client` em `core/models.py`; `LeadViewSet.convert`; `DealSerializer`;
`AddNegocio.tsx` com `RemoteCombobox` de clientes.

### 1.3 Dois responsáveis que não conversam `[impacto alto] [esforço P]` — **bug de dado**

**Hoje.** `Lead.responsible` é FK para `Broker` (cadastro de Pessoas → Corretores);
`Lead.assigned_to` é FK para `User` do tipo BROKER, preenchido pela fila. O serviço da fila
(`core/services/queue.py`) nunca toca em `responsible`. O relatório "Desempenho de Corretores"
([reports.py:261](trustimovel-api/core/views/reports.py#L261)) agrupa só por `responsible`.
Resultado: lead distribuído pela roleta **não conta** para o corretor no relatório, e a
conversão em negócio herda `responsible` vazio.

**Sugestão.**
- Curto prazo: `convert` e o relatório passam a considerar `assigned_to` quando `responsible`
  está vazio (ou o serviço da fila copia o corretor para `responsible` ao aceitar).
- Longo prazo: unificar o conceito. O "corretor" do CRM deveria ser o `User` BROKER, e o cadastro
  de Pessoas → Corretores ficar só como captador do imóvel. Um campo por model, não dois.

**Onde mexer.** `core/services/queue.py` (`accept`, `assign`); `LeadViewSet.convert`;
`ReportsView._brokers`; `Deal.responsible`.

### 1.4 Sem detecção de duplicidade `[impacto médio] [esforço P]`

**Hoje.** Cadastrar lead com telefone ou e-mail já existente passa em silêncio. A regra de
retorno da fila (`returning_broker` em `core/services/queue.py`) já compara telefone e e-mail
na janela configurada, mas o cadastro não usa isso.

**Sugestão.** No `POST /leads/`, devolver aviso (não erro) com os leads que batem por telefone
normalizado ou e-mail; o painel mostra "já existe LEAD012, deseja abrir ou continuar?". Uma
action `merge` para juntar dois leads, preservando as duas timelines, fecha o ciclo.

**Onde mexer.** `LeadSerializer.validate`; endpoint `GET /leads/duplicates/?phone=&email=`;
`AddLead.tsx`.

### 1.5 Atendimentos e Leads são duas fichas da mesma pessoa `[impacto médio] [esforço M]`

**Hoje.** `ServiceTicket` tem nome, telefone e e-mail próprios e uma timeline (`messages`)
separada da timeline do lead (`interactions`). A própria doc
([atendimentos.md](trustimovel-vite/docs/crm/atendimentos.md)) já registra a intenção de fundir.

**Sugestão.** Primeiro passo: `ServiceTicket.lead` e `ServiceTicket.client` como FKs opcionais,
com preenchimento automático dos dados de contato ao escolher. Segundo passo: uma "ficha da
pessoa" que mostre as duas timelines mescladas por data.

**Onde mexer.** `core/models.py`; `ServiceTicketSerializer`; `AddAtendimento.tsx`.

---

## 2. Fluxo do dia a dia

### 2.1 Entrada de lead é toda manual `[impacto alto] [esforço M]`

**Hoje.** Todas as rotas exigem JWT ([urls.py](trustimovel-api/config/urls.py)); lançar na fila
(`POST /queue/leads/`) exige gestor. As origens `SITE`, `PORTALS` e `WHATSAPP` existem só como
rótulo do select. O formulário do site da imobiliária não tem para onde mandar o contato.

**Sugestão.** Endpoint público `POST /public/leads/` autenticado por chave por imobiliária
(campo novo em `AgencySettings`, gerado no painel), protegido pelo reCAPTCHA cujas chaves
(`recaptcha_site_key`, `recaptcha_secret_key`) **já existem** em `AgencySettings`. O endpoint cria o
lead com `source=SITE` (ou o que vier no payload), vincula o imóvel pelo código (item 1.1) e chama
`queue_service.enqueue`. Throttle por IP e por chave. Depois, o mesmo endpoint serve de destino
para integrações com portais (webhook do ZAP/OLX, etc.).

**Onde mexer.** `core/views/public.py` novo; `AgencySettings.public_api_key`; throttle scope em
`config/settings.py`; tela de Configurações mostra a chave e um exemplo de `<form>`.

### 2.2 O relógio da fila não tem cron `[impacto alto] [esforço P]`

**Hoje.** O comando `queuetick` existe, mas não está agendado em nenhum lugar: nem no
`Dockerfile`, nem nos dois `docker-compose.yml`, nem no Railway. Sem ninguém com a tela da fila
aberta, ofertas não expiram, SLAs não estouram e leads na espera não são redistribuídos.

**Sugestão.** Agendar `python manage.py queuetick` a cada minuto: serviço de cron no Railway, ou
um container `cron` no compose, ou um `while true; do ...; sleep 60; done` num serviço separado.
Documentar no `CLAUDE.md` da API que a fila **depende** desse agendamento.

**Onde mexer.** Infra (Railway/compose); `trustimovel-api/CLAUDE.md`.

### 2.3 Cada tela aberta roda o relógio `[impacto médio] [esforço P]`

**Hoje.** `GET /queue/` chama `queue_service.tick` a cada leitura
([queue.py:53](trustimovel-api/core/views/queue.py#L53)), e o painel consulta a cada 5 s
([queue-store.ts:30](trustimovel-vite/src/lib/queue-store.ts#L30)). O `tick`
([queue.py:487](trustimovel-api/core/services/queue.py#L487)) abre transação com
`select_for_update` em todos os leads abertos da imobiliária. Com dez pessoas na tela, são dois
locks por segundo na mesma faixa de linhas.

**Sugestão.** Com o cron no lugar (2.2), o tick da leitura passa a ser só um "adiantamento":
guardar em cache (`django.core.cache`, por `agency_id`) o instante do último tick e só rodar de
novo se passaram mais de N segundos. Alternativa mais ambiciosa: trocar polling por SSE
(`StreamingHttpResponse`) e o painel só recebe quando algo muda.

**Onde mexer.** `QueueViewSet.list`; `config/settings.py` (`CACHES`).

### 2.4 A oferta só chega por polling `[impacto alto] [esforço P a M]`

**Hoje.** O corretor só sabe que recebeu uma oferta se estiver com a tela da fila aberta e
olhando. Não há som, notificação do navegador, e-mail nem WhatsApp. Com o prazo de aceite curto
(padrão de poucos minutos), quem está em outra aba perde a vez e ainda leva "vez perdida".

**Sugestão, em camadas.**
1. **Na tela (P):** ao detectar transição para `OFFERED` do usuário logado, tocar um som e
   disparar `Notification` do navegador (pedir permissão na primeira visita à fila). Título da aba
   piscando "(1) Nova oferta".
2. **Fora da tela (M):** e-mail via `services_emails.py` e/ou mensagem de WhatsApp por API
   (Twilio, Z-API, Evolution) com link direto para aceitar. Isso pede um worker ou envio no
   próprio `tick`, com cuidado para não bloquear a requisição.
3. **Escala (G):** SSE ou WebSocket no lugar do polling.

**Onde mexer.** `FilaAtendimento.tsx` / `queue-store.ts` (comparar estado anterior e atual);
`core/services/queue.py` (`dispatch`) para disparar o aviso; `services_emails.py`.

### 2.5 Primeiro contato depende de registro manual `[impacto alto] [esforço P]`

**Hoje.** O botão de WhatsApp da fila e de Leads abre `wa.me` e não grava nada. O SLA de primeira
resposta só para quando o corretor volta e registra uma ação à mão. Quem esquece estoura o SLA
mesmo tendo falado com o cliente.

**Sugestão.** Ao clicar em WhatsApp, ligar ou e-mail, o painel chama
`POST /queue/leads/{id}/notes/` (ou `/leads/{id}/interactions/`) com um texto padrão
("Abriu conversa no WhatsApp") antes de abrir o link. Isso marca o primeiro contato e ainda
enriquece a timeline. Um `LeadInteraction.Type.CONTACT_ATTEMPT` separaria essas entradas
automáticas das anotações escritas.

**Onde mexer.** `Leads.tsx`, `FilaAtendimento.tsx`; opcionalmente `LeadInteraction.Type`.

### 2.6 Tarefas sem lembrete nem automação `[impacto alto] [esforço M]`

**Hoje.** `Task` é um cadastro passivo: nada avisa que venceu, e nada cria tarefa a partir de um
evento do CRM. Não há recorrência.

**Sugestão.**
- **Automações simples, no serviço da fila e no funil:** lead aceito cria "Follow-up em 24h";
  negócio movido para "Visita agendada" cria tarefa do tipo Visita com o imóvel; negócio parado
  há N dias cria "Retomar contato".
- **Agenda do dia por e-mail** (um comando `sendagenda` no cron das 7h): tarefas de hoje e
  atrasadas, por corretor.
- **Recorrência** só se pedido: campo `recurrence` (diária/semanal/mensal) e o cron gera a
  próxima ao concluir.

**Onde mexer.** `core/services/queue.py` (`accept`), `DealSerializer.update` (mudança de
`stage`), comando novo em `core/management/commands/`.

### 2.7 E-mail só existe para redefinir senha `[impacto médio] [esforço P cada]`

**Hoje.** `core/services/services_emails.py` tem um único envio. `AgencySettings` já tem
`sender_email`, `sender_name` e `cc_email`, sem uso no CRM.

**Sugestão.** Templates para: novo lead (para o gestor), oferta recebida (corretor), SLA estourado
(gestor), resumo diário (gestor: leads do dia, taxa de aceite, negócios ganhos). Todos opcionais,
ligados por flag em Configurações.

**Onde mexer.** `services_emails.py`, `core/template_emails/`, `AgencySettings`.

---

## 3. Telas e relatórios

### 3.1 Indicadores calculados no navegador sobre uma página só `[impacto alto] [esforço M]`

**Hoje.** Leads, Funil, Tarefas e Atendimentos usam `CatalogPagination`
([property.py:170](trustimovel-api/core/views/property.py#L170)), que devolve a primeira página
de 200 registros, e os cards somam em cima disso no cliente
([Leads.tsx:181](trustimovel-vite/src/pages/Leads.tsx#L181)). Passado o limite, os cards mostram
números errados e a lista trunca **sem aviso**. Uma imobiliária média chega a 200 leads em poucos
meses.

**Sugestão.** Endpoint de sumário por recurso (`GET /leads/summary/`, `/deals/summary/`, etc.)
com as contagens por status/etapa e somas de valor, no mesmo espírito de `/dashboard/`. As
listas voltam para a paginação padrão de 15 com controle de página (o `CatalogCrudList` já sabe
fazer). O Funil, que precisa do quadro inteiro, pode manter página grande mas mostrar um aviso
"exibindo os 200 negócios mais recentes" quando `count > items.length`.

**Onde mexer.** Actions `summary` nos quatro viewsets de `crm.py`; as quatro telas.

### 3.2 Listagem carrega a timeline inteira `[impacto médio] [esforço P]`

**Hoje.** `LeadSerializer` embute `interactions` e `ServiceTicketSerializer` embute `messages`
em toda listagem ([crm.py](trustimovel-api/core/serializers/crm.py)). Cada lead da fila gera
várias interações; em um ano, o `GET /leads/` carrega milhares de linhas para desenhar uma tabela.

**Sugestão.** Serializer de lista sem a timeline (só `interactions_count` e a última), e o
serializer completo no `retrieve`. O painel de detalhe (Sheet) passa a buscar `/leads/{id}/`
em vez de ler da lista viva.

**Onde mexer.** `get_serializer_class` em `LeadViewSet` e `ServiceTicketViewSet`; `Leads.tsx`.

### 3.3 Sem filtro por período `[impacto médio] [esforço P]`

**Hoje.** `filterset_fields` só aceita valor exato (`status`, `source`, `responsible`...).
Não dá para listar leads criados na semana, tarefas de um intervalo nem negócios com
previsão de fechamento no mês. `Task` filtra `due_date` só por igualdade.

**Sugestão.** `FilterSet` por model em `core/filters.py` com `created_after`/`created_before`,
`due_after`/`due_before`, `estimated_close_after`/`_before`, `last_contact_before` (para
"sem contato há X dias"). O painel ganha um seletor de período ao lado da busca.

**Onde mexer.** `core/filters.py`; `filterset_class` nos viewsets; as telas.

### 3.4 Corretor vê e edita todos os leads `[impacto médio] [esforço P]`

**Hoje.** `LeadViewSet.get_queryset` não restringe por `assigned_to`; um usuário BROKER vê e
edita todos os leads da imobiliária. A fila faz o contrário
([queue.py:232](trustimovel-api/core/views/queue.py#L232)): o corretor só vê o que está com ele.
A tela de Leads também não tem filtro "meus".

**Sugestão.** Decidir o produto. Se corretor deve ver tudo, ao menos um filtro rápido "Meus leads"
(`assigned_to=<eu>`) como padrão para BROKER. Se não deve, uma configuração em `AgencySettings`
(`brokers_see_all_leads`) aplicada no `get_queryset`, valendo para `Deal` e `Task` também.

**Onde mexer.** `LeadViewSet.get_queryset`; `Leads.tsx`; opcionalmente `AgencySettings`.

### 3.5 Funil sem histórico de etapa `[impacto médio] [esforço M]`

**Hoje.** Mover o cartão é um `PATCH stage` sem rastro. Não há equivalente ao
`PropertyHistory` para `Deal`, então não existe tempo por etapa, quem moveu nem quando. O
relatório "Taxas de Conversão por Estágio" só consegue olhar a etapa atual. O cartão também não
mostra "parado há N dias".

**Sugestão.** `DealStageChange` (deal, from_stage, to_stage, user, created_at), gravado em
`DealSerializer.update` quando `stage` muda, ou reutilizar o padrão de
`core/services/property_history.py`. Com isso: tempo médio por etapa no relatório, "parado há 12
dias" em vermelho no cartão, e filtro "sem movimento há mais de X dias".

**Onde mexer.** `core/models.py`; `DealSerializer.update`; `ReportsView._funnel`;
`FunilVendas.tsx`.

### 3.6 Relatórios que faltam `[impacto médio] [esforço M]`

**Hoje.** `/reports/` traz vendas, imóveis, leads por origem/status, corretores e funil.

**Sugestão.**
- **Conversão por origem:** para cada `source`, leads → negócios → ganhos e valor. É a pergunta
  central de marketing imobiliário ("qual canal paga?") e os dados já estão em `Lead.source` e
  `Deal.origin`.
- **SLA por corretor no período:** tempo médio de aceite e de primeira resposta, taxa de aceite,
  vezes perdidas. Hoje a fila mostra só o dia; os carimbos (`offered_at`, `accepted_at`,
  `contacted_at`) já existem no `Lead`.
- **Motivos de perda por corretor e por origem**, cruzando `loss_reason`.
- **Exportar CSV** nas listas de leads, negócios e tarefas (action `export` com o mesmo
  `FilterSet` da listagem).

**Onde mexer.** `core/views/reports.py`; `Relatorios.tsx`; actions `export` em `crm.py`.

### 3.7 Theo só lê `[impacto baixo] [esforço M]`

**Hoje.** O assistente ([assistant.py](trustimovel-api/core/services/assistant.py)) tem
ferramentas de consulta (`query_records`, `get_record`, `dashboard_summary`, `sales_report`).

**Sugestão.** Duas ferramentas de escrita, sempre com confirmação na tela antes de executar:
`add_lead_interaction` e `create_task`. "Theo, anota que o cliente do LEAD045 pediu retorno
sexta" vira interação + tarefa. Respeitar o `ResourcePermission` de cada recurso como as
ferramentas de leitura já fazem.

**Onde mexer.** `core/services/assistant.py`; `TheoChat.tsx` (passo de confirmação).

---

## 4. Documentação

- O `CLAUDE.md` da raiz aponta a API para `trust-imovel-django/`, pasta que está **vazia**. A API
  vive em [trustimovel-api/](trustimovel-api/). A pasta `trustimovel-mpc/` também está vazia.
  Corrigir os links da raiz e remover ou explicar as pastas vazias.
- `trustimovel-vite/docs/README.md` ainda diz que "as demais telas gravam em localStorage"; hoje
  só Portais/Exportadores faz isso. Atualizar o parágrafo "Estado geral".

---

## Roteiro sugerido

| Fase | Itens | Resultado |
| --- | --- | --- |
| **1. Fila confiável** | 2.2, 2.4 (camada 1), 2.5, 2.3 | Oferta chega, SLA anda sozinho, primeiro contato registrado sem esforço |
| **2. Dado correto** | 1.3, 3.1, 3.2 | Relatório de corretores certo, cards certos com qualquer volume, listagem leve |
| **3. Captação** | 2.1, 1.4 | Lead do site entra sozinho na fila, sem duplicar |
| **4. Vínculos** | 1.1, 1.2, 1.5 | Imóvel, cliente e atendimento ligados ao lead; ficha única da pessoa |
| **5. Produtividade** | 2.6, 2.7, 3.3, 3.4 | Follow-up automático, e-mails, filtros por período, "meus leads" |
| **6. Análise** | 3.5, 3.6, 3.7 | Tempo por etapa, conversão por canal, CSV, Theo que escreve |

Cada fase é entregável sozinha e não depende da seguinte, com uma exceção: a fase 4 (item 1.1)
facilita muito a fase 3 (o lead do site já chega com o imóvel vinculado), então vale pelo menos
criar a FK antes de abrir o endpoint público.
