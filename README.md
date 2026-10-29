# TicketFlash

API de venda de ingressos (Checkpoint 3) com **FastAPI**, **MongoDB** como fonte da verdade e **Redis** para cache, reservas temporárias, ranking, rate limit e Pub/Sub.

## Integrantes

| Nome | RM |
| --- | --- |
| Pedro Henrique de Oliveira | RM00000 |
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

Todas as requisições estão em [`requests.http`](requests.http).

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
