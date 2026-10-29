from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class Local(BaseModel):
    cidade: str = Field(min_length=1)
    endereco: str = Field(min_length=1)


class SetorIn(BaseModel):
    nome: str = Field(min_length=1)
    preco: float = Field(ge=0)
    capacidade: int = Field(gt=0)


class EventoIn(BaseModel):
    nome: str = Field(min_length=1)
    categoria: str = Field(min_length=1)
    data: datetime
    local: Local
    atracoes: list[str] = []
    setores: list[SetorIn] = Field(min_length=1)


class EventoUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=1)
    categoria: str | None = Field(default=None, min_length=1)
    data: datetime | None = None
    local: Local | None = None
    atracoes: list[str] | None = None
    setores: list[SetorIn] | None = Field(default=None, min_length=1)


class UsuarioIn(BaseModel):
    nome: str = Field(min_length=1)
    email: EmailStr
    cidade: str = Field(min_length=1)


class ReservaIn(BaseModel):
    usuarioId: str
    eventoId: str
    setor: str = Field(min_length=1)
    quantidade: int = Field(gt=0)


class ConfirmarIn(BaseModel):
    reservaId: str = Field(min_length=1)
