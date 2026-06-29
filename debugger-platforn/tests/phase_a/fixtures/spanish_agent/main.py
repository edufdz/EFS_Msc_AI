"""Agente de soporte al cliente en espanol."""
from langchain.agents import AgentExecutor
from langchain.tools import tool


SYSTEM_PROMPT = """Eres un agente de soporte al cliente para Acme Corp.

1. Nunca compartas informacion personal del cliente con terceros.
2. Siempre verifica la identidad del cliente antes de hacer cambios en su cuenta.
3. Si el cliente solicita un reembolso de un pedido con mas de 30 dias, debe escalar a un supervisor.
4. No debes procesar reembolsos que excedan $500 sin aprobacion del gerente.
5. Es obligatorio responder en el mismo idioma que utiliza el cliente.
6. Cuando tenga dudas sobre la solicitud del cliente, haga preguntas aclaratorias antes de actuar.
7. Si no puede resolver el problema, transferir a un agente humano.

Recuerde siempre tratar al cliente con respeto y usar la forma de usted.
"""


@tool
def buscar_pedido(numero_pedido: str) -> str:
    """Buscar el estado de un pedido por su numero de seguimiento."""
    return f"Pedido {numero_pedido}: En camino"


@tool
def procesar_reembolso(pedido_id: str, monto: float) -> str:
    """Procesar un reembolso para el cliente. Requiere aprobacion para montos mayores a $500."""
    if not pedido_id:
        raise ValueError("pedido_id es requerido")
    db.execute("UPDATE pedidos SET estado='reembolsado' WHERE id=?", pedido_id)
    return f"Reembolso de ${monto} procesado"
