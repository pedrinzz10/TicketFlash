"""Escuta o canal pedidos:confirmados e imprime cada pedido.

Uso: docker compose exec api python subscriber.py
"""
import json

from app.db import CANAL_PEDIDOS, r


def main() -> None:
    pubsub = r.pubsub()
    pubsub.subscribe(CANAL_PEDIDOS)
    print(f"Inscrito em '{CANAL_PEDIDOS}'. Aguardando pedidos... (Ctrl+C para sair)", flush=True)
    try:
        for mensagem in pubsub.listen():
            if mensagem["type"] != "message":
                continue
            pedido = json.loads(mensagem["data"])
            print(
                f"[pedido confirmado] {pedido['id']} | evento {pedido['eventoId']} | "
                f"setor {pedido['setor']} x{pedido['quantidade']} | R$ {pedido['valorTotal']:.2f}",
                flush=True,
            )
            print(json.dumps(pedido, ensure_ascii=False, indent=2), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        pubsub.close()


if __name__ == "__main__":
    main()
