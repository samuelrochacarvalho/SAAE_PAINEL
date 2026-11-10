from Adafruit_IO import MQTTClient
from config import USUARIO, CHAVE
from banco import inicializar_banco, salvar_dado

FEEDS = [
    "estacao-heartbeat",
    "bombacorrego",
    "estadorele",
    "nivelalta",
    "nivelquadrada",
    "sirene",
    "statussirene"
]

# A inicializacao acontece uma unica vez por execucao do programa.
primeira_conexao = True
aguardando_inicializacao = set()


def conectado(cliente):
    global primeira_conexao

    print("Conectado ao Adafruit IO!")

    for feed in FEEDS:
        cliente.subscribe(feed)
        print("Inscrito:", feed)

    if primeira_conexao:
        primeira_conexao = False
        aguardando_inicializacao.update(FEEDS)

        for feed in FEEDS:
            cliente.publish(feed + "/get", "")
            print("Solicitando ultimo estado:", feed)
    else:
        print("Reconexao MQTT: sem nova inicializacao.")


def desconectado(cliente):
    print("Desconectado do Adafruit IO!")


def mensagem(cliente, feed_id, payload):
    if feed_id not in FEEDS:
        return

    origem = (
        "INICIALIZACAO"
        if feed_id in aguardando_inicializacao
        else "MQTT"
    )

    try:
        salvar_dado(feed_id, payload, origem)
    except Exception as erro:
        print(f"Erro ao salvar {feed_id} no SQLite: {erro}")
        return

    if origem == "INICIALIZACAO":
        aguardando_inicializacao.discard(feed_id)

    print(f"[{feed_id}] {payload} - gravado no SQLite ({origem})")


inicializar_banco()

cliente = MQTTClient(USUARIO, CHAVE)
cliente.on_connect = conectado
cliente.on_disconnect = desconectado
cliente.on_message = mensagem

print("Conectando ao Adafruit IO...")
cliente.connect()
cliente.loop_blocking()
