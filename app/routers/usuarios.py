from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pymongo.errors import DuplicateKeyError

from app.db import db, serializar
from app.schemas import UsuarioIn

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.post("", status_code=201)
def criar_usuario(usuario: UsuarioIn):
    doc = {**usuario.model_dump(), "dataCadastro": datetime.now(timezone.utc)}
    try:
        db.usuarios.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail=f"Email já cadastrado: {usuario.email}")
    return serializar(doc)


@router.get("")
def listar_usuarios():
    return [serializar(doc) for doc in db.usuarios.find().sort("nome", 1)]
