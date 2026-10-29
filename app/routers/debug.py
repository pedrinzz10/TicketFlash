from fastapi import APIRouter

from app.db import db

router = APIRouter(prefix="/debug", tags=["debug"])


def estagios(plano: dict) -> list[str]:
    """Achata a árvore do plano em 'ESTAGIO(indice)', do topo para as folhas."""
    saida = []
    no = plano.get("queryPlan", plano)
    while no:
        estagio = no.get("stage", "?")
        if "indexName" in no:
            estagio += f"({no['indexName']})"
        saida.append(estagio)
        no = no.get("inputStage")
    return saida


@router.get("/explain")
def explain(categoria: str = "show"):
    plano = db.eventos.find({"categoria": categoria}).sort("data", 1).explain()
    winning = plano["queryPlanner"]["winningPlan"]
    return {
        "query": {"find": {"categoria": categoria}, "sort": {"data": 1}},
        "estagios": estagios(winning),
        "winningPlan": winning,
    }
