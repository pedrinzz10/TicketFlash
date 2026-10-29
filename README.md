# TicketFlash

API de venda de ingressos (Checkpoint 3) com **FastAPI**, **MongoDB** como fonte da verdade e **Redis** para cache, reservas temporárias, ranking, rate limit e Pub/Sub.

## Integrantes

| Nome | RM |
| --- | --- |
| Pedro Henrique de Oliveira | RM562312 |
| _Nome do integrante_ | RM00000 |
| _Nome do integrante_ | RM00000 |

## Como executar

Pré-requisito: Docker com Docker Compose.

```bash
docker compose up -d --build              # sobe api, mongo e redis
docker compose exec api python seed.py    # 10 eventos, 20 usuários, 51 pedidos
```

A API fica em http://localhost:8000 (Swagger em http://localhost:8000/docs). O seed apaga e recria os dados, limpa o Redis e imprime ids de exemplo para usar no `requests.http`.

Comandos úteis para a demonstração:

```bash
docker compose exec redis redis-cli TTL reserva:<reservaId>   # TTL da reserva (~600)
docker compose exec redis redis-cli TTL evento:<eventoId>     # TTL do cache (~60)
docker compose exec redis redis-cli ZREVRANGE ranking:eventos 0 4 WITHSCORES
docker compose exec api python subscriber.py                  # bônus Pub/Sub
```

Para demonstrar o **410** sem esperar 10 minutos, suba com um TTL curto de reserva:

```bash
RESERVA_TTL=20 docker compose up -d      # PowerShell: $env:RESERVA_TTL=20; docker compose up -d
```

Variáveis de ambiente da API: `MONGO_URL` (padrão `mongodb://mongo:27017` no compose), `MONGO_DB`, `REDIS_URL` (`redis://redis:6379/0`) e `RESERVA_TTL` (padrão 600).

## Endpoints

| Método | Rota | Descrição | Códigos |
| --- | --- | --- | --- |
| POST | `/eventos` | Cria evento com setores embutidos (`vendidos` = 0) | 201, 422 |
| GET | `/eventos?categoria=&cidade=` | Lista eventos, filtrando na query do `find` | 200 |
| GET | `/eventos/ranking` | Top 5 mais vistos (`ZREVRANGE ... WITHSCORES`) | 200 |
| GET | `/eventos/{id}` | Consulta com cache-aside (`origem`: `banco` ou `cache`) e `ZINCRBY` no ranking | 200, 400, 404 |
| PUT | `/eventos/{id}` | Atualiza (`update_one`) e invalida `evento:{id}` | 200, 400, 404, 422 |
| DELETE | `/eventos/{id}` | Remove, apaga o cache e tira o id do ranking | 200, 400, 404 |
| POST | `/reservas` | Rate limit → validação → vagas → `SET NX EX` | 201, 404, 409, 422, 429 |
| GET | `/reservas/{reservaId}` | Dados da reserva e `ttl` restante | 200, 404 |
| POST | `/pedidos/confirmar` | `GETDEL` da reserva, `$inc` condicional, grava pedido, invalida cache, `PUBLISH` | 201, 404, 409, 410 |
| GET | `/relatorios/faturamento` | Faturamento por evento (aggregation com `$lookup`) | 200 |
| GET | `/relatorios/ocupacao/{eventoId}` | Percentual vendido por setor (aggregation) | 200, 400, 404 |
| GET | `/debug/explain?categoria=show` | `winningPlan` de `find({categoria}).sort(data)` | 200 |
| GET | `/usuarios` | Lista usuários (apoio para pegar ids) | 200 |
| POST | `/usuarios` | Cria usuário; email repetido viola o índice único | 201, 409, 422 |

Todas as requisições estão em [`requests.http`](requests.http) e na coleção Postman [`TicketFlash.postman_collection.json`](TicketFlash.postman_collection.json).

## Coleção Postman

### Como usar

1. Suba o ambiente e rode o seed (veja [Como executar](#como-executar)).
2. No Postman, vá em **Import** e selecione `TicketFlash.postman_collection.json`.
3. Rode o request **0. Setup → Carregar ids do seed**. Ele preenche as variáveis da coleção `eventoId` (Rock in Concert), `usuarioId`, `outroUsuarioId` e `rateLimitUsuarioId`, sem precisar colar ids.
4. Siga as pastas na ordem: **1. Eventos**, **2. Usuários**, **3. Reservas**, **4. Pedidos**, **5. Relatórios e índices**.

Sempre que rodar o seed de novo, rode o **0. Setup** outra vez, porque os ids mudam.

### O que cada request faz sozinho

| Request | Comportamento |
| --- | --- |
| UC-01 Criar evento | Salva o id em `novoEventoId`, usado pelos requests de DELETE. |
| UC-03 Consultar evento (rode 2x) | 1ª execução responde `origem: banco`; a 2ª, em até 60 s, `origem: cache`. |
| UC-04 Atualizar evento | Depois dele, o UC-03 volta a responder `origem: banco` com o nome novo. |
| UC-07 Criar reserva | Salva o `reservaId` e mostra no Console o comando `TTL reserva:<id>` para o redis-cli. |
| UC-07 Rate limit | O pre-request dispara 10 reservas do mesmo usuário (os códigos aparecem no Console) e o request é a 11ª, que dá **429**. Para repetir, espere 60 s. |
| UC-09 Confirmar pedido | Confirma a reserva salva pelo UC-07. Rodar de novo dá **410**. |
| UC-13 Explain | Confere que o plano usa `IXSCAN(categoria_1_data_1)` e não usa `COLLSCAN`. |

Todos os requests têm teste do código de status esperado, exibido em **Test Results**. Os logs dos scripts ficam no **Console** (View → Show Postman Console).

### Reserva expirada (410)

Com o TTL padrão a reserva dura 10 minutos. Para demonstrar o 410 rapidamente:

1. Suba a API com TTL curto. Só a API reinicia e os dados continuam.
   - Git Bash: `RESERVA_TTL=15 docker compose up -d`
   - PowerShell: `$env:RESERVA_TTL=15; docker compose up -d`
2. Rode **UC-07 Criar reserva**, espere 15 s e rode **UC-09 Confirmar reserva expirada**.
3. Volte ao TTL padrão. Git Bash: `docker compose up -d`. PowerShell: `Remove-Item Env:RESERVA_TTL; docker compose up -d`.

### Rodar a coleção inteira

No Postman, use **Run collection**. Pela linha de comando, com o [Newman](https://www.npmjs.com/package/newman):

```bash
newman run TicketFlash.postman_collection.json
```

A execução cria eventos e reservas e renomeia o Rock in Concert. Rode o seed de novo antes de gravar o vídeo.

## Modelagem

### MongoDB

| Coleção | Campos | Relação | Índices |
| --- | --- | --- | --- |
| `eventos` | nome, categoria, data, local {cidade, endereco}, atracoes [], setores [{nome, preco, capacidade, vendidos}] | Setores **embutidos** | Composto `(categoria, data)` |
| `usuarios` | nome, email, cidade, dataCadastro | Independente | Único em `email` |
| `pedidos` | usuarioId, eventoId, setor, quantidade, valorTotal, status, criadoEm | **Referencia** usuário e evento | `usuarioId` |

- **Setores embutidos no evento:** são sempre lidos junto com o evento, são poucos e limitados, e o `$inc` em `setores.$.vendidos` precisa ser atômico no mesmo documento que guarda a `capacidade`. Com o filtro `$elemMatch` (`vendidos <= capacidade - quantidade`) o MongoDB checa e incrementa numa única operação, então confirmações simultâneas nunca passam da capacidade.
- **Pedidos referenciados:** crescem sem limite (embutir estouraria o documento de 16 MB) e são consultados por conta própria em relatórios e histórico. `usuarioId` e `eventoId` são `ObjectId`, o que permite o `$lookup` em `eventos`.
- **Índices:** criados no startup da API (e novamente pelo seed). O composto `(categoria, data)` atende o filtro por categoria já ordenado por data sem `SORT` em memória; o único em `email` impede cadastro duplicado; o de `usuarioId` atende o histórico de pedidos de um usuário.

### Redis

| Chave | Estrutura | TTL | Uso |
| --- | --- | --- | --- |
| `evento:{id}` | String (JSON) | 60 s | Cache do `GET /eventos/{id}` |
| `reserva:{reservaId}` | String (JSON) via `SET NX EX` | 600 s | Reserva temporária |
| `ranking:eventos` | Sorted Set | — | Contagem de visualizações |
| `limite:{usuarioId}` | String via `INCR` + `EXPIRE` | 60 s | Rate limit (10 reservas por janela) |
| `pedidos:confirmados` | Canal Pub/Sub | — | Aviso de pedido confirmado |

Nada permanente fica só no Redis: se ele for zerado, perde-se apenas cache, ranking, contadores e reservas ainda não pagas.

- **Confirmação idempotente:** `GETDEL` lê e apaga a reserva numa operação só; uma segunda confirmação (ou uma reserva expirada) recebe **410**.
- **Preço confiável:** o `valorTotal` é calculado com o `preco` do setor lido no MongoDB, nunca com valor vindo do cliente.
- **Pub/Sub tolerante a falha:** um erro no `PUBLISH` é registrado no log e não desfaz o pedido já gravado.

## Saída do explain

`GET /debug/explain?categoria=show` executa `db.eventos.find({categoria: "show"}).sort({data: 1}).explain()`. O plano vencedor usa **IXSCAN** no índice composto, sem `COLLSCAN` nem `SORT` em memória:

```json
{
  "query": { "find": { "categoria": "show" }, "sort": { "data": 1 } },
  "estagios": ["FETCH", "IXSCAN(categoria_1_data_1)"],
  "winningPlan": {
    "stage": "FETCH",
    "inputStage": {
      "stage": "IXSCAN",
      "keyPattern": { "categoria": 1, "data": 1 },
      "indexName": "categoria_1_data_1",
      "isMultiKey": false,
      "multiKeyPaths": { "categoria": [], "data": [] },
      "isUnique": false,
      "isSparse": false,
      "isPartial": false,
      "indexVersion": 2,
      "direction": "forward",
      "indexBounds": {
        "categoria": ["[\"show\", \"show\"]"],
        "data": ["[MinKey, MaxKey]"]
      }
    }
  }
}
```

## Estrutura

```
app/
  main.py          # FastAPI + criação de índices no startup
  db.py            # conexões, constantes, helpers de ObjectId e serialização
  schemas.py       # modelos Pydantic (validações 422)
  routers/         # eventos, usuarios, reservas, pedidos, relatorios, debug
seed.py            # dados iniciais
subscriber.py      # consumidor do canal pedidos:confirmados
requests.http      # todas as requisições
Dockerfile
docker-compose.yml
requirements.txt
```

## Entrega

- Repositório: _link do GitHub_
- Vídeo: _link do vídeo_
