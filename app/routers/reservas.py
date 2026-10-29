import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.db import RATE_LIMIT_JANELA, RATE_LIMIT_MAX, RESERVA_TTL, db, parse_oid, r
from app.schemas import ReservaIn

router = APIRouter(prefix="/reservas", tags=["reservas"])


def reserva_key(reserva_id: str) -> str:
    return f"reserva:{reserva_id}"


@router.post("", status_code=201)
def criar_reserva(reserva: ReservaIn):
    # 1. Rate limit por usuário: janela fixa de 60 s iniciada na primeira reserva.
    limite_key = f"limite:{reserva.usuarioId}"
    tentativas = r.incr(limite_key)
    if tentativas == 1:
        r.expire(limite_key, RATE_LIMIT_JANELA)
    if tentativas > RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=f"Limite de {RATE_LIMIT_MAX} reservas em {RATE_LIMIT_JANELA} s excedido",
        )

    # 2. Usuário, evento e setor existem.
    if not db.usuarios.find_one({"_id": parse_oid(reserva.usuarioId)}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    evento = db.eventos.find_one({"_id": parse_oid(reserva.eventoId)}, {"setores": 1})
    if not evento:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    setor = next((s for s in evento["setores"] if s["nome"] == reserva.setor), None)
    if not setor:
        raise HTTPException(status_code=404, detail=f"Setor não encontrado: {reserva.setor}")

    # 3. Vagas.
    disponiveis = setor["capacidade"] - setor["vendidos"]
    if disponiveis < reserva.quantidade:
        raise HTTPException(status_code=409, detail=f"Setor sem vagas suficientes (disponíveis: {disponiveis})")

    # 4. Reserva temporária no Redis.
    reserva_id = str(uuid.uuid4())
    dados = {
        **reserva.model_dump(),
        "reservaId": reserva_id,
        "criadaEm": datetime.now(timezone.utc).isoformat(),
    }
    if not r.set(reserva_key(reserva_id), json.dumps(dados), nx=True, ex=RESERVA_TTL):
        raise HTTPException(status_code=409, detail="Conflito ao gerar a reserva, tente novamente")

    return {**dados, "expiraEm": RESERVA_TTL}


@router.get("/{reserva_id}")
def consultar_reserva(reserva_id: str):
    dados = r.get(reserva_key(reserva_id))
    if not dados:
        raise HTTPException(status_code=404, detail="Reserva expirada ou inexistente")
    return {**json.loads(dados), "ttl": r.ttl(reserva_key(reserva_id))}
