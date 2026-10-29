import json

from fastapi import APIRouter, HTTPException

from app.db import CACHE_TTL, RANKING_KEY, db, parse_oid, r, serializar
from app.schemas import EventoIn, EventoUpdate

router = APIRouter(prefix="/eventos", tags=["eventos"])


def cache_key(evento_id: str) -> str:
    return f"evento:{evento_id}"


@router.post("", status_code=201)
def criar_evento(evento: EventoIn):
    doc = evento.model_dump()
    for setor in doc["setores"]:
        setor["vendidos"] = 0
    resultado = db.eventos.insert_one(doc)
    doc["_id"] = resultado.inserted_id
    return serializar(doc)


@router.get("")
def listar_eventos(categoria: str | None = None, cidade: str | None = None):
    filtro = {}
    if categoria:
        filtro["categoria"] = categoria
    if cidade:
        filtro["local.cidade"] = cidade
    return [serializar(doc) for doc in db.eventos.find(filtro).sort("data", 1)]


# Declarada antes de /{evento_id} para "ranking" não ser tratado como id.
@router.get("/ranking")
def ranking():
    top = r.zrevrange(RANKING_KEY, 0, 4, withscores=True)
    if not top:
        return []
    ids = [parse_oid(evento_id) for evento_id, _ in top]
    nomes = {str(doc["_id"]): doc["nome"] for doc in db.eventos.find({"_id": {"$in": ids}}, {"nome": 1})}
    return [
        {"id": evento_id, "nome": nomes.get(evento_id), "visualizacoes": int(score)}
        for evento_id, score in top
    ]


@router.get("/{evento_id}")
def consultar_evento(evento_id: str):
    oid = parse_oid(evento_id)

    em_cache = r.get(cache_key(evento_id))
    if em_cache:
        r.zincrby(RANKING_KEY, 1, evento_id)
        return {**json.loads(em_cache), "origem": "cache"}

    doc = db.eventos.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Evento não encontrado")

    evento = serializar(doc)
    r.set(cache_key(evento_id), json.dumps(evento), ex=CACHE_TTL)
    r.zincrby(RANKING_KEY, 1, evento_id)
    return {**evento, "origem": "banco"}


@router.put("/{evento_id}")
def atualizar_evento(evento_id: str, dados: EventoUpdate):
    oid = parse_oid(evento_id)
    alteracoes = dados.model_dump(exclude_unset=True)
    if not alteracoes:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    atual = db.eventos.find_one({"_id": oid})
    if not atual:
        raise HTTPException(status_code=404, detail="Evento não encontrado")

    if "setores" in alteracoes:
        # Preserva o que já foi vendido em setores que continuam existindo.
        vendidos = {s["nome"]: s.get("vendidos", 0) for s in atual["setores"]}
        for setor in alteracoes["setores"]:
            setor["vendidos"] = vendidos.get(setor["nome"], 0)
            if setor["capacidade"] < setor["vendidos"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Capacidade do setor {setor['nome']} menor que os {setor['vendidos']} já vendidos",
                )

    db.eventos.update_one({"_id": oid}, {"$set": alteracoes})
    r.delete(cache_key(evento_id))
    return serializar(db.eventos.find_one({"_id": oid}))


@router.delete("/{evento_id}")
def remover_evento(evento_id: str):
    oid = parse_oid(evento_id)
    resultado = db.eventos.delete_one({"_id": oid})
    if resultado.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    r.delete(cache_key(evento_id))
    r.zrem(RANKING_KEY, evento_id)
    return {"detail": "Evento removido", "id": evento_id}
