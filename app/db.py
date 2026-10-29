import os

import redis
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from pymongo import ASCENDING, MongoClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "ticketflash")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

RESERVA_TTL = int(os.getenv("RESERVA_TTL", "600"))
CACHE_TTL = 60
RATE_LIMIT_MAX = 10
RATE_LIMIT_JANELA = 60
RANKING_KEY = "ranking:eventos"
CANAL_PEDIDOS = "pedidos:confirmados"

mongo = MongoClient(MONGO_URL)
db = mongo[MONGO_DB]
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def ensure_indexes() -> None:
    db.usuarios.create_index("email", unique=True)
    db.eventos.create_index([("categoria", ASCENDING), ("data", ASCENDING)])
    db.pedidos.create_index("usuarioId")


def parse_oid(valor: str) -> ObjectId:
    try:
        return ObjectId(valor)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Id inválido: {valor}")


def serializar(doc: dict) -> dict:
    """Converte um documento do MongoDB em JSON: _id vira id e ObjectId/datetime viram string."""
    saida = {}
    for chave, valor in doc.items():
        if chave == "_id":
            saida["id"] = str(valor)
        elif isinstance(valor, ObjectId):
            saida[chave] = str(valor)
        elif hasattr(valor, "isoformat"):
            saida[chave] = valor.isoformat()
        else:
            saida[chave] = valor
    return saida
