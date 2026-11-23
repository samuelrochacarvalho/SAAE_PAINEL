"""Cliente MQTT do painel SAAE. Não envia comandos de acionamento."""
import logging
from logging.handlers import RotatingFileHandler
import time
from pathlib import Path
from Adafruit_IO import MQTTClient
from config import USUARIO, CHAVE
from banco import inicializar_banco, salvar_dado

FEEDS = ("estacao-heartbeat", "bombacorrego", "estadorele", "nivelalta",
         "nivelquadrada", "sirene", "statussirene")
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("saae.mqtt")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = RotatingFileHandler(LOG_DIR / "mqtt.log", maxBytes=2_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


def conectado(cliente):
    logger.info("Conectado ao Adafruit IO; restaurando assinaturas")
    for feed in FEEDS:
        try:
            cliente.subscribe(feed)
            logger.info("Assinado: %s", feed)
        except Exception:
            logger.exception("Falha ao assinar %s", feed)
    # Solicitar os estados retidos dos dispositivos, sem criar um heartbeat novo.
    # /get é apenas consulta; NUNCA publicar nos feeds de comando aqui.
    for feed in FEEDS:
        if feed == "estacao-heartbeat":
            continue
        try:
            cliente.publish(feed + "/get", "")
            logger.info("Consulta de estado solicitada: %s", feed)
        except Exception:
            logger.exception("Falha na consulta de %s", feed)


def desconectado(cliente):
    logger.warning("Cliente MQTT desconectado")


def mensagem(cliente, feed_id, payload):
    if feed_id not in FEEDS:
        return
    try:
        # Evitar marcar resposta /get como heartbeat novo.
        # Para outros feeds, uma resposta de /get é um estado conhecido,
        # não necessariamente um evento físico recente.
        salvar_dado(feed_id, payload, "MQTT")
        logger.info("Recebido %s = %s; gravado no SQLite", feed_id, payload)
    except Exception:
        logger.exception("Erro ao gravar feed %s", feed_id)


def main():
    inicializar_banco()
    espera = 3
    while True:
        cliente = None
        try:
            logger.info("Iniciando conexão MQTT")
            cliente = MQTTClient(USUARIO, CHAVE)
            cliente.on_connect = conectado
            cliente.on_disconnect = desconectado
            cliente.on_message = mensagem
            cliente.connect()
            espera = 3
            cliente.loop_blocking()
            logger.warning("Loop MQTT terminou inesperadamente")
        except (KeyboardInterrupt, SystemExit):
            logger.info("Encerramento solicitado")
            raise
        except Exception:
            logger.exception("Erro no cliente MQTT; tentando recuperar")
        finally:
            if cliente is not None:
                try:
                    cliente.disconnect()
                except Exception:
                    pass
        logger.warning("Nova tentativa MQTT em %s segundos", espera)
        time.sleep(espera)
        espera = min(espera * 2, 60)


if __name__ == "__main__":
    main()
