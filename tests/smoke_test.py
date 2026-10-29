"""Smoke test de ponta a ponta contra a API viva, conferindo o estado real do MongoDB e do Redis.

Uso (dentro do container, onde MONGO_URL, REDIS_URL e RESERVA_TTL já estão definidos):
    docker compose exec api python tests/smoke_test.py

Rode o seed antes. O teste cria eventos, usuários e pedidos: rode o seed de novo antes de gravar o vídeo.
"""
import os
import sys
import threading
import time
import traceback
import uuid

import redis
import requests
from bson import ObjectId
from pymongo import MongoClient

API = os.getenv("API_URL", "http://localhost:8000")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "ticketflash")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RESERVA_TTL = int(os.getenv("RESERVA_TTL", "600"))

db = MongoClient(MONGO_URL)[MONGO_DB]
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

resultados: list[bool] = []


def check(nome: str, condicao, motivo: str = "") -> bool:
    ok = bool(condicao)
    resultados.append(ok)
    print(f"  {'✅' if ok else '❌'} {nome}" + ("" if ok else f" — {motivo}"))
    return ok


def api(metodo: str, caminho: str, **kwargs) -> requests.Response:
    return requests.request(metodo, API + caminho, timeout=10, **kwargs)


def corpo_evento(nome: str, capacidade: int = 100) -> dict:
    return {
        "nome": nome,
        "categoria": "smoke",
        "data": "2026-12-05T20:00:00",
        "local": {"cidade": "Recife", "endereco": "Rua do Teste, 1"},
        "atracoes": ["Banda Teste"],
        "setores": [{"nome": "Pista", "preco": 75.5, "capacidade": capacidade}],
    }


def novo_usuario() -> str:
    resp = api("POST", "/usuarios", json={
        "nome": "Smoke Test",
        "email": f"smoke-{uuid.uuid4().hex[:10]}@smoke-test.com",
        "cidade": "Recife",
    })
    resp.raise_for_status()
    return resp.json()["id"]


def reservar(usuario_id: str, evento_id: str, setor: str = "Pista", quantidade: int = 1) -> requests.Response:
    return api("POST", "/reservas", json={
        "usuarioId": usuario_id, "eventoId": evento_id, "setor": setor, "quantidade": quantidade,
    })


def vendidos(evento_id: str, setor: str) -> int:
    evento = db.eventos.find_one({"_id": ObjectId(evento_id)})
    return next(s["vendidos"] for s in evento["setores"] if s["nome"] == setor)


def chaves_reserva() -> set[str]:
    return set(r.scan_iter("reserva:*"))


# ---------------------------------------------------------------- Eventos

def testar_eventos(rock_id: str) -> None:
    print("\nEventos (Req 2, 5, 7, 9)")

    resp = api("POST", "/eventos", json=corpo_evento("Smoke Evento"))
    criado = resp.json()
    check("POST /eventos válido → 201", resp.status_code == 201, f"{resp.status_code} {resp.text}")
    evento_id = criado["id"]
    doc = db.eventos.find_one({"_id": ObjectId(evento_id)})
    check("setores gravados embutidos com vendidos = 0",
          doc and all(s["vendidos"] == 0 for s in doc["setores"]), f"documento: {doc}")

    resp = api("POST", "/eventos", json={"nome": "Sem campos obrigatórios"})
    check("POST /eventos sem campos obrigatórios → 422", resp.status_code == 422, str(resp.status_code))
    invalido = corpo_evento("Inválido")
    invalido["setores"] = [{"nome": "Pista", "preco": -1, "capacidade": 0}]
    resp = api("POST", "/eventos", json=invalido)
    check("POST /eventos com capacidade 0 e preço negativo → 422", resp.status_code == 422, str(resp.status_code))

    for params, filtro in [
        ({"categoria": "show"}, {"categoria": "show"}),
        ({"cidade": "Curitiba"}, {"local.cidade": "Curitiba"}),
        ({"categoria": "show", "cidade": "Curitiba"}, {"categoria": "show", "local.cidade": "Curitiba"}),
    ]:
        lista = api("GET", "/eventos", params=params).json()
        esperados = {str(d["_id"]) for d in db.eventos.find(filtro, {"_id": 1})}
        recebidos = {e["id"] for e in lista}
        bate = all(
            e["categoria"] == params.get("categoria", e["categoria"])
            and e["local"]["cidade"] == params.get("cidade", e["local"]["cidade"])
            for e in lista
        )
        check(f"GET /eventos?{'&'.join(f'{k}={v}' for k, v in params.items())} retorna só e todos os que batem",
              lista and bate and recebidos == esperados,
              f"recebidos {len(recebidos)}, esperados {len(esperados)}, todos batem: {bate}")

    r.delete(f"evento:{evento_id}")
    primeira = api("GET", f"/eventos/{evento_id}").json()
    segunda = api("GET", f"/eventos/{evento_id}").json()
    check("GET /eventos/{id}: 1ª origem banco, 2ª origem cache",
          (primeira.get("origem"), segunda.get("origem")) == ("banco", "cache"),
          f"{primeira.get('origem')}, {segunda.get('origem')}")
    ttl = r.ttl(f"evento:{evento_id}")
    check("chave evento:{id} no Redis com TTL entre 1 e 60", 1 <= ttl <= 60, f"TTL = {ttl}")

    resp = api("PUT", f"/eventos/{evento_id}", json={"nome": "Smoke Evento Editado"})
    check("PUT /eventos/{id} → 200", resp.status_code == 200, f"{resp.status_code} {resp.text}")
    check("PUT apagou a chave evento:{id}", r.exists(f"evento:{evento_id}") == 0, "chave ainda existe")
    depois = api("GET", f"/eventos/{evento_id}").json()
    check("GET após PUT volta com origem banco e o nome novo",
          depois.get("origem") == "banco" and depois.get("nome") == "Smoke Evento Editado",
          f"origem {depois.get('origem')}, nome {depois.get('nome')}")

    resp = api("GET", "/eventos/abc")
    check("GET /eventos/abc (id mal formatado) → 400", resp.status_code == 400, str(resp.status_code))
    inexistente = str(ObjectId())
    resp = api("GET", f"/eventos/{inexistente}")
    check("GET /eventos/{id inexistente} → 404 e fora do ranking",
          resp.status_code == 404 and r.zscore("ranking:eventos", inexistente) is None,
          f"{resp.status_code}, score {r.zscore('ranking:eventos', inexistente)}")

    # Consulta o Rock in Concert até ele ultrapassar o líder atual do ranking.
    topo = r.zrevrange("ranking:eventos", 0, 0, withscores=True)
    lider = topo[0][1] if topo else 0
    atual = r.zscore("ranking:eventos", rock_id) or 0
    for _ in range(int(lider - atual) + 3):
        api("GET", f"/eventos/{rock_id}")
    ranking = api("GET", "/eventos/ranking").json()
    views = [item["visualizacoes"] for item in ranking]
    check("GET /eventos/ranking: no máximo 5 itens em ordem decrescente",
          0 < len(ranking) <= 5 and views == sorted(views, reverse=True), f"{ranking}")
    check("evento mais consultado no teste aparece no topo",
          ranking and ranking[0]["id"] == rock_id and ranking[0]["nome"] == "Rock in Concert", f"topo: {ranking[:1]}")

    api("GET", f"/eventos/{evento_id}")  # garante cache e ranking antes de remover
    resp = api("DELETE", f"/eventos/{evento_id}")
    check("DELETE /eventos/{id} → 200", resp.status_code in (200, 204), f"{resp.status_code} {resp.text}")
    check("DELETE apagou o cache e tirou o id do ranking",
          r.exists(f"evento:{evento_id}") == 0 and r.zscore("ranking:eventos", evento_id) is None,
          f"cache {r.exists(f'evento:{evento_id}')}, score {r.zscore('ranking:eventos', evento_id)}")
    resp = api("GET", f"/eventos/{evento_id}")
    check("GET após DELETE → 404", resp.status_code == 404, str(resp.status_code))


# ---------------------------------------------------------------- Reservas

def testar_reservas(rock_id: str) -> None:
    print("\nReservas (Req 6, 8)")

    usuario = novo_usuario()
    resp = reservar(usuario, rock_id, quantidade=2)
    check("POST /reservas → 201", resp.status_code == 201, f"{resp.status_code} {resp.text}")
    reserva_id = resp.json().get("reservaId")
    ttl = r.ttl(f"reserva:{reserva_id}")
    check(f"chave reserva:{{id}} no Redis com 0 < TTL ≤ {RESERVA_TTL}",
          0 < ttl <= RESERVA_TTL, f"TTL = {ttl}")

    antes = chaves_reserva()
    resp = reservar(usuario, rock_id, setor="Backstage")
    check("Backstage lotado → 409", resp.status_code == 409, f"{resp.status_code} {resp.text}")
    novas = chaves_reserva() - antes
    check("nenhuma chave reserva:* nova após o 409", not novas, f"novas: {novas}")

    limitado = novo_usuario()
    codigos = [reservar(limitado, rock_id).status_code for _ in range(11)]
    check("rate limit: 10 primeiras → 201 e a 11ª → 429",
          codigos[:10] == [201] * 10 and codigos[10] == 429, f"{codigos}")
    outro = reservar(novo_usuario(), rock_id)
    check("outro usuário reservando ao mesmo tempo não é bloqueado", outro.status_code == 201,
          f"{outro.status_code} {outro.text}")

    espera = r.ttl(f"limite:{limitado}")
    print(f"  … aguardando {espera + 1} s para a janela do rate limit expirar")
    time.sleep(max(espera, 0) + 1)
    resp = reservar(limitado, rock_id)
    check("após o TTL de limite:{usuarioId}, o usuário volta a reservar", resp.status_code == 201,
          f"{resp.status_code} {resp.text}")


# ---------------------------------------------------------------- Pedidos

def confirmar(reserva_id: str) -> requests.Response:
    return api("POST", "/pedidos/confirmar", json={"reservaId": reserva_id})


def testar_pedidos(rock_id: str) -> None:
    print("\nPedidos (Req 10 + bônus)")

    usuario = novo_usuario()
    quantidade = 3
    preco = next(s["preco"] for s in db.eventos.find_one({"_id": ObjectId(rock_id)})["setores"] if s["nome"] == "Pista")
    reserva_id = reservar(usuario, rock_id, quantidade=quantidade).json()["reservaId"]
    api("GET", f"/eventos/{rock_id}")  # popula o cache para provar que a confirmação o invalida
    antes = vendidos(rock_id, "Pista")

    resp = confirmar(reserva_id)
    pedido = resp.json()
    check("confirmar reserva válida → 201", resp.status_code == 201, f"{resp.status_code} {resp.text}")
    check(f"vendidos aumentou exatamente {quantidade}", vendidos(rock_id, "Pista") == antes + quantidade,
          f"antes {antes}, depois {vendidos(rock_id, 'Pista')}")
    check("chave reserva:{id} sumiu do Redis", r.exists(f"reserva:{reserva_id}") == 0, "chave ainda existe")
    check("valorTotal = preço do setor × quantidade",
          pedido.get("valorTotal") == round(preco * quantidade, 2),
          f"{pedido.get('valorTotal')} ≠ {preco} × {quantidade}")
    gravado = db.pedidos.find_one({"_id": ObjectId(pedido["id"])}) if "id" in pedido else None
    check("pedido gravado no MongoDB com status confirmado",
          gravado and gravado["status"] == "confirmado", f"{gravado}")
    check("cache evento:{id} apagado pela confirmação", r.exists(f"evento:{rock_id}") == 0, "chave ainda existe")
    depois = api("GET", f"/eventos/{rock_id}").json()
    setor = next(s for s in depois["setores"] if s["nome"] == "Pista")
    check("GET do evento logo após confirmar → origem banco com vendidos atualizado",
          depois.get("origem") == "banco" and setor["vendidos"] == antes + quantidade,
          f"origem {depois.get('origem')}, vendidos {setor['vendidos']}")

    resp = confirmar(reserva_id)
    check("confirmar a mesma reserva de novo → 410", resp.status_code == 410, f"{resp.status_code} {resp.text}")

    expirada = reservar(usuario, rock_id, quantidade=2).json()["reservaId"]
    print(f"  … aguardando {RESERVA_TTL + 2} s para a reserva expirar")
    time.sleep(RESERVA_TTL + 2)
    pedidos_antes = db.pedidos.count_documents({})
    vendidos_antes = vendidos(rock_id, "Pista")
    resp = confirmar(expirada)
    check("confirmar reserva expirada → 410", resp.status_code == 410, f"{resp.status_code} {resp.text}")
    check("nenhum pedido novo e vendidos inalterado após o 410",
          db.pedidos.count_documents({}) == pedidos_antes and vendidos(rock_id, "Pista") == vendidos_antes,
          f"pedidos {pedidos_antes}→{db.pedidos.count_documents({})}, "
          f"vendidos {vendidos_antes}→{vendidos(rock_id, 'Pista')}")

    testar_concorrencia()


def testar_concorrencia() -> None:
    capacidade, tentativas = 5, 8
    evento_id = api("POST", "/eventos", json=corpo_evento("Smoke Concorrência", capacidade)).json()["id"]
    reservas = [reservar(novo_usuario(), evento_id).json()["reservaId"] for _ in range(tentativas)]

    codigos: list[int] = []
    largada = threading.Barrier(tentativas)

    def disparar(reserva_id: str) -> None:
        largada.wait()
        codigos.append(confirmar(reserva_id).status_code)

    threads = [threading.Thread(target=disparar, args=(rid,)) for rid in reservas]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = vendidos(evento_id, "Pista")
    pedidos = db.pedidos.count_documents({"eventoId": ObjectId(evento_id)})
    check(f"concorrência: {tentativas} confirmações paralelas → exatamente {capacidade} × 201 e o resto 409",
          codigos.count(201) == capacidade and codigos.count(409) == tentativas - capacidade,
          f"{sorted(codigos)}")
    check(f"vendidos termina em {capacidade} (nunca passa da capacidade) com {capacidade} pedidos gravados",
          final == capacidade and pedidos == capacidade, f"vendidos {final}, pedidos {pedidos}")


# ---------------------------------------------------------------- main

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Smoke test contra {API} (RESERVA_TTL={RESERVA_TTL})")

    rock = db.eventos.find_one({"nome": "Rock in Concert"})
    if not rock or db.usuarios.count_documents({}) < 20:
        print("❌ Seed não encontrado: rode `docker compose exec api python seed.py` antes.")
        return 1
    rock_id = str(rock["_id"])

    for secao in (testar_eventos, testar_reservas, testar_pedidos):
        try:
            secao(rock_id)
        except Exception as erro:
            check(f"{secao.__name__} terminou sem exceção", False, repr(erro))
            traceback.print_exc()

    passaram = sum(resultados)
    print(f"\nResumo: {passaram} de {len(resultados)} passaram")
    if passaram < len(resultados):
        print("Alguns casos falharam.")
    print("Rode o seed de novo antes de gravar o vídeo (o teste deixa eventos, usuários e pedidos extras).")
    return 0 if passaram == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
