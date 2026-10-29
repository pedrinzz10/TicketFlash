"""Popula o MongoDB com 10 eventos, 20 usuários e 50+ pedidos e limpa o Redis.

Uso: docker compose exec api python seed.py
"""
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.db import db, ensure_indexes, r

rng = random.Random(42)

CIDADES = {
    "São Paulo": ["Allianz Parque, Av. Francisco Matarazzo 1705", "Teatro Renault, Av. Brig. Luís Antônio 411"],
    "Rio de Janeiro": ["Jeunesse Arena, Av. Embaixador Abelardo Bueno 3401", "Vivo Rio, Av. Infante Dom Henrique 85"],
    "Belo Horizonte": ["Mineirão, Av. Antônio Abrahão Caram 1001"],
    "Curitiba": ["Pedreira Paulo Leminski, R. João Gava 970"],
}

EVENTOS = [
    ("Rock in Concert", "show", "São Paulo", ["Banda Aurora", "Os Ventos"]),
    ("Noite do Samba", "show", "Rio de Janeiro", ["Grupo Raiz", "Mart'nália Cover"]),
    ("Festival de Verão", "festival", "Rio de Janeiro", ["DJ Maré", "Coletivo Sol", "Banda Brisa"]),
    ("Hamlet Contemporâneo", "teatro", "São Paulo", ["Cia. Palco Aberto"]),
    ("Final Estadual de Futebol", "esporte", "Belo Horizonte", ["Atlético x Cruzeiro"]),
    ("Risadaria", "stand-up", "São Paulo", ["Ana Riso", "Beto Piada"]),
    ("Sertanejo Universitário", "show", "Belo Horizonte", ["Dupla Horizonte"]),
    ("Curitiba Jazz Festival", "festival", "Curitiba", ["Quarteto Araucária", "Big Band Sul"]),
    ("O Fantasma da Ópera", "teatro", "Rio de Janeiro", ["Cia. Lírica Carioca"]),
    ("Electro Night", "show", "Curitiba", ["DJ Pinhão", "Synth Club"]),
]

SETORES = [
    {"nome": "Pista", "preco": 180.0, "capacidade": 500},
    {"nome": "Arquibancada", "preco": 120.0, "capacidade": 800},
    {"nome": "Camarote", "preco": 450.0, "capacidade": 60},
]

NOMES = [
    "Ana Souza", "Bruno Lima", "Carla Dias", "Diego Rocha", "Elisa Prado", "Felipe Melo",
    "Gabriela Nunes", "Henrique Alves", "Isabela Costa", "João Pereira", "Karina Lopes",
    "Lucas Martins", "Mariana Freitas", "Nicolas Barros", "Olivia Teixeira", "Paulo Ribeiro",
    "Queila Santos", "Rafael Gomes", "Sofia Carvalho", "Thiago Moreira",
]


def main() -> None:
    for colecao in ("eventos", "usuarios", "pedidos"):
        db[colecao].delete_many({})
    r.flushdb()
    ensure_indexes()

    agora = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    usuarios = []
    for i, nome in enumerate(NOMES):
        primeiro, ultimo = nome.lower().split()
        usuarios.append({
            "_id": ObjectId(),
            "nome": nome,
            "email": f"{primeiro}.{ultimo}@email.com",
            "cidade": rng.choice(list(CIDADES)),
            "dataCadastro": agora - timedelta(days=rng.randint(1, 365)),
        })

    eventos = []
    for i, (nome, categoria, cidade, atracoes) in enumerate(EVENTOS):
        eventos.append({
            "_id": ObjectId(),
            "nome": nome,
            "categoria": categoria,
            "data": (agora + timedelta(days=15 + i * 9)).replace(hour=20, minute=0, second=0),
            "local": {"cidade": cidade, "endereco": rng.choice(CIDADES[cidade])},
            "atracoes": atracoes,
            "setores": [{**s, "vendidos": 0} for s in SETORES],
        })
    # Setor minúsculo e já lotado no primeiro evento, para demonstrar o 409.
    eventos[0]["setores"].append({"nome": "Backstage", "preco": 900.0, "capacidade": 2, "vendidos": 0})

    pedidos = []
    for _ in range(50):
        evento = rng.choice(eventos)
        setor = rng.choice(SETORES)
        quantidade = rng.randint(1, 4)
        pedidos.append({
            "usuarioId": rng.choice(usuarios)["_id"],
            "eventoId": evento["_id"],
            "setor": setor["nome"],
            "quantidade": quantidade,
            "valorTotal": round(setor["preco"] * quantidade, 2),
            "status": "cancelado" if rng.random() < 0.15 else "confirmado",
            "criadoEm": agora - timedelta(minutes=rng.randint(1, 60 * 24 * 30)),
        })
    pedidos.append({
        "usuarioId": usuarios[0]["_id"],
        "eventoId": eventos[0]["_id"],
        "setor": "Backstage",
        "quantidade": 2,
        "valorTotal": 1800.0,
        "status": "confirmado",
        "criadoEm": agora - timedelta(days=1),
    })

    # vendidos = soma das quantidades dos pedidos confirmados de cada setor.
    vendidos = defaultdict(int)
    for pedido in pedidos:
        if pedido["status"] == "confirmado":
            vendidos[(pedido["eventoId"], pedido["setor"])] += pedido["quantidade"]
    for evento in eventos:
        for setor in evento["setores"]:
            setor["vendidos"] = vendidos[(evento["_id"], setor["nome"])]

    db.usuarios.insert_many(usuarios)
    db.eventos.insert_many(eventos)
    db.pedidos.insert_many(pedidos)

    print(f"Inseridos {len(eventos)} eventos, {len(usuarios)} usuários e {len(pedidos)} pedidos.")
    print(f"Evento de exemplo:  {eventos[0]['_id']}  ({eventos[0]['nome']}, setor Backstage lotado)")
    print(f"Usuário de exemplo: {usuarios[0]['_id']}  ({usuarios[0]['email']})")
    print(f"Outro usuário:      {usuarios[1]['_id']}  ({usuarios[1]['email']})")


if __name__ == "__main__":
    main()
