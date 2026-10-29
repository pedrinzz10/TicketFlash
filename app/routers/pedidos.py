import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.db import CANAL_PEDIDOS, db, parse_oid, r, serializar
from app.schemas import ConfirmarIn

router = APIRouter(prefix="/pedidos", tags=["pedidos"])
log = logging.getLogger("uvicorn.error")


@router.post("/confirmar", status_code=201)
def confirmar_pedido(body: ConfirmarIn):
    # 1-2. Lê e apaga a reserva atomicamente: a mesma reserva nunca é confirmada duas vezes.
    bruto = r.getdel(f"reserva:{body.reservaId}")
    if not bruto:
        raise HTTPException(status_code=410, detail="Reserva expirada ou inexistente")
    reserva = json.loads(bruto)

    evento_oid = parse_oid(reserva["eventoId"])
    evento = db.eventos.find_one({"_id": evento_oid}, {"setores": 1})
    if not evento:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    setor = next((s for s in evento["setores"] if s["nome"] == reserva["setor"]), None)
    if not setor:
        raise HTTPException(status_code=404, detail=f"Setor não encontrado: {reserva['setor']}")

    # 3-4. Incremento condicional e atômico: só soma se ainda couber na capacidade.
    quantidade = reserva["quantidade"]
    capacidade = setor["capacidade"]
    resultado = db.eventos.update_one(
        {
            "_id": evento_oid,
            "setores": {
                "$elemMatch": {
                    "nome": reserva["setor"],
                    "capacidade": capacidade,
                    "vendidos": {"$lte": capacidade - quantidade},
                }
            },
        },
        {"$inc": {"setores.$.vendidos": quantidade}},
    )
    if resultado.modified_count == 0:
        raise HTTPException(status_code=409, detail="Setor sem vagas suficientes")

    # 5. Pedido com o preço do setor gravado no MongoDB.
    pedido = {
        "usuarioId": parse_oid(reserva["usuarioId"]),
        "eventoId": evento_oid,
        "setor": reserva["setor"],
        "quantidade": quantidade,
        "valorTotal": round(setor["preco"] * quantidade, 2),
        "status": "confirmado",
        "criadoEm": datetime.now(timezone.utc),
    }
    db.pedidos.insert_one(pedido)
    resposta = serializar(pedido)

    # 6. O vendidos mudou: invalida o cache do evento.
    r.delete(f"evento:{reserva['eventoId']}")

    # 7. Bônus: avisa os inscritos. Uma falha aqui não desfaz a venda.
    try:
        r.publish(CANAL_PEDIDOS, json.dumps(resposta))
    except Exception:
        log.exception("Falha ao publicar pedido %s em %s", resposta["id"], CANAL_PEDIDOS)

    return resposta
