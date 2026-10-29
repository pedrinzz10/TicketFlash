from fastapi import APIRouter, HTTPException

from app.db import db, parse_oid

router = APIRouter(prefix="/relatorios", tags=["relatorios"])


@router.get("/faturamento")
def faturamento():
    pipeline = [
        {"$match": {"status": "confirmado"}},
        {"$group": {"_id": "$eventoId", "faturamento": {"$sum": "$valorTotal"}}},
        {"$lookup": {"from": "eventos", "localField": "_id", "foreignField": "_id", "as": "evento"}},
        {"$unwind": "$evento"},
        {
            "$project": {
                "_id": 0,
                "eventoId": {"$toString": "$_id"},
                "nome": "$evento.nome",
                "faturamento": {"$round": ["$faturamento", 2]},
            }
        },
        {"$sort": {"faturamento": -1}},
    ]
    return list(db.pedidos.aggregate(pipeline))


@router.get("/ocupacao/{evento_id}")
def ocupacao(evento_id: str):
    pipeline = [
        {"$match": {"_id": parse_oid(evento_id)}},
        {"$unwind": "$setores"},
        {
            "$project": {
                "_id": 0,
                "setor": "$setores.nome",
                "capacidade": "$setores.capacidade",
                "vendidos": "$setores.vendidos",
                "percentual": {
                    "$round": [
                        {"$multiply": [{"$divide": ["$setores.vendidos", "$setores.capacidade"]}, 100]},
                        2,
                    ]
                },
            }
        },
    ]
    setores = list(db.eventos.aggregate(pipeline))
    if not setores:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    return setores
