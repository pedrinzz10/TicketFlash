from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import ensure_indexes
from app.routers import debug, eventos, pedidos, relatorios, reservas, usuarios


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_indexes()
    yield


app = FastAPI(title="TicketFlash", lifespan=lifespan)

app.include_router(eventos.router)
app.include_router(usuarios.router)
app.include_router(reservas.router)
app.include_router(pedidos.router)
app.include_router(relatorios.router)
app.include_router(debug.router)
