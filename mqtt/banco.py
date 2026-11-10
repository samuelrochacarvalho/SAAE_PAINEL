
import sqlite3
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
CAMINHO_BANCO = BASE_DIR / "dados" / "saae.db"

FEEDS = [
    "estacao-heartbeat",
    "bombacorrego",
    "estadorele",
    "nivelalta",
    "nivelquadrada",
    "sirene",
    "statussirene"
]

# Nome da tabela correspondente a cada feed
TABELAS = {
    "estacao-heartbeat": "estacao_heartbeat",
    "bombacorrego": "bombacorrego",
    "estadorele": "estadorele",
    "nivelalta": "nivelalta",
    "nivelquadrada": "nivelquadrada",
    "sirene": "sirene",
    "statussirene": "statussirene"
}


def conectar():
    CAMINHO_BANCO.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    return sqlite3.connect(CAMINHO_BANCO, timeout=10)


def inicializar_banco():
    with conectar() as conn:
        for tabela in TABELAS.values():
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {tabela} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    valor TEXT NOT NULL,
                    data_hora TEXT NOT NULL,
                    origem TEXT NOT NULL
                )
            """)


def salvar_dado(feed, valor, origem="MQTT"):
    if feed not in TABELAS:
        return

    if origem not in ("MQTT", "INICIALIZACAO"):
        raise ValueError("Origem inválida")

    tabela = TABELAS[feed]

    data_hora = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    with conectar() as conn:
        conn.execute(
            f"""
            INSERT INTO {tabela}
                (valor, data_hora, origem)
            VALUES (?, ?, ?)
            """,
            (str(valor), data_hora, origem)
        )


if __name__ == "__main__":
    inicializar_banco()
    print("Banco SQLite inicializado com sucesso!")
    print("Local:", CAMINHO_BANCO)
