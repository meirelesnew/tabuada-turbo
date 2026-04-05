from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import random
import string
import uuid
import os

MONGO_URL = os.environ.get("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL não configurada nas variáveis de ambiente")
client = MongoClient(MONGO_URL)
db = client["tabuada2026"]

jogadores_col = db["jogadores"]
salas_col     = db["salas"]
ranking_col   = db["ranking"]

app = FastAPI(title="Tabuada Turbo API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── MODELS ──────────────────────────────────────────────────────────
class JogadorIn(BaseModel):
    nome: str
    avatar: str

class CriarSalaIn(BaseModel):
    jogador_id: str
    nome: str
    avatar: str
    nivel: int

class EntrarSalaIn(BaseModel):
    codigo: str
    jogador_id: str
    nome: str
    avatar: str

class FinalizarIn(BaseModel):
    codigo: str
    jogador_id: str
    tempo: int
    acertos: int
    erros: int

class RankingIn(BaseModel):
    jogador_id: str
    nome: str
    avatar: str
    nivel: int
    tempo: int
    acertos: int
    erros: int
    modo: str

# ── HELPERS ─────────────────────────────────────────────────────────
def gerar_codigo():
    letras = ''.join(random.choices(string.ascii_uppercase, k=5))
    nums   = ''.join(random.choices(string.digits, k=3))
    return f"{letras}-{nums}"

# ── HEALTH ──────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "app": "Tabuada Turbo API v1.0"}

@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok", "db": "conectado"}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

# ── JOGADOR ─────────────────────────────────────────────────────────
@app.post("/jogador/salvar")
def salvar_jogador(body: JogadorIn):
    jid = str(uuid.uuid4())
    doc = {
        "_id": jid,
        "nome": body.nome,
        "avatar": body.avatar,
        "criado_em": datetime.utcnow().isoformat()
    }
    jogadores_col.replace_one({"_id": jid}, doc, upsert=True)
    return {"jogador_id": jid, "nome": body.nome, "avatar": body.avatar}

# ── BATALHA: CRIAR SALA ─────────────────────────────────────────────
@app.post("/batalha/criar")
def criar_sala(body: CriarSalaIn):
    codigo = gerar_codigo()
    while salas_col.find_one({"codigo": codigo, "status": {"$ne": "finalizada"}}):
        codigo = gerar_codigo()

    expira_em = datetime.utcnow() + timedelta(minutes=30)
    sala = {
        "_id": str(uuid.uuid4()),
        "codigo": codigo,
        "nivel": body.nivel,
        "status": "aguardando",
        "criado_em": datetime.utcnow().isoformat(),
        "expira_em": expira_em.isoformat(),
        "jogadores": [
            {
                "id": body.jogador_id,
                "nome": body.nome,
                "avatar": body.avatar,
                "tempo": None,
                "acertos": None,
                "erros": None,
                "finalizado": False,
                "entrou_em": datetime.utcnow().isoformat()
            }
        ]
    }
    salas_col.insert_one(sala)
    return {"codigo": codigo, "nivel": body.nivel, "status": "aguardando"}

# ── BATALHA: ENTRAR NA SALA ─────────────────────────────────────────
@app.post("/batalha/entrar")
def entrar_sala(body: EntrarSalaIn):
    sala = salas_col.find_one({"codigo": body.codigo.upper()})
    if not sala:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    if sala["status"] == "finalizada":
        raise HTTPException(status_code=400, detail="Sala já finalizada")
    if sala["status"] == "em_jogo":
        raise HTTPException(status_code=400, detail="Partida já iniciada")

    ids_na_sala = [j["id"] for j in sala["jogadores"]]
    if body.jogador_id not in ids_na_sala:
        novo = {
            "id": body.jogador_id,
            "nome": body.nome,
            "avatar": body.avatar,
            "tempo": None,
            "acertos": None,
            "erros": None,
            "finalizado": False,
            "entrou_em": datetime.utcnow().isoformat()
        }
        salas_col.update_one(
            {"codigo": body.codigo.upper()},
            {"$push": {"jogadores": novo}}
        )

    sala_att = salas_col.find_one({"codigo": body.codigo.upper()})
    return {
        "codigo": sala_att["codigo"],
        "nivel": sala_att["nivel"],
        "status": sala_att["status"],
        "jogadores": sala_att["jogadores"]
    }

# ── BATALHA: STATUS (polling a cada 2s) ────────────────────────────
@app.get("/batalha/{codigo}")
def status_sala(codigo: str):
    sala = salas_col.find_one({"codigo": codigo.upper()})
    if not sala:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    return {
        "codigo": sala["codigo"],
        "nivel": sala["nivel"],
        "status": sala["status"],
        "jogadores": sala["jogadores"]
    }

# ── BATALHA: INICIAR ───────────────────────────────────────────────
@app.post("/batalha/{codigo}/iniciar")
def iniciar_sala(codigo: str):
    sala = salas_col.find_one({"codigo": codigo.upper()})
    if not sala:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    if len(sala["jogadores"]) < 2:
        raise HTTPException(status_code=400, detail="Aguardando mais jogadores")
    salas_col.update_one(
        {"codigo": codigo.upper()},
        {"$set": {"status": "em_jogo", "iniciado_em": datetime.utcnow().isoformat()}}
    )
    return {"status": "em_jogo"}

# ── BATALHA: FINALIZAR ─────────────────────────────────────────────
@app.post("/batalha/finalizar")
def finalizar_jogador(body: FinalizarIn):
    sala = salas_col.find_one({"codigo": body.codigo.upper()})
    if not sala:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    salas_col.update_one(
        {"codigo": body.codigo.upper(), "jogadores.id": body.jogador_id},
        {"$set": {
            "jogadores.$.tempo": body.tempo,
            "jogadores.$.acertos": body.acertos,
            "jogadores.$.erros": body.erros,
            "jogadores.$.finalizado": True
        }}
    )

    sala_att = salas_col.find_one({"codigo": body.codigo.upper()})
    todos_prontos = all(j["finalizado"] for j in sala_att["jogadores"])
    if todos_prontos:
        salas_col.update_one(
            {"codigo": body.codigo.upper()},
            {"$set": {"status": "finalizada"}}
        )

    # Salvar no ranking
    jogador_info = next((j for j in sala_att["jogadores"] if j["id"] == body.jogador_id), {})
    ranking_col.insert_one({
        "_id": str(uuid.uuid4()),
        "jogador_id": body.jogador_id,
        "nome": jogador_info.get("nome", "?"),
        "avatar": jogador_info.get("avatar", "🦁"),
        "nivel": sala_att["nivel"],
        "tempo": body.tempo,
        "acertos": body.acertos,
        "erros": body.erros,
        "modo": "batalha",
        "data": datetime.utcnow().strftime("%d/%m/%Y")
    })

    sala_final = salas_col.find_one({"codigo": body.codigo.upper()})
    return {
        "status": sala_final["status"],
        "jogadores": sala_final["jogadores"]
    }

# ── RANKING: SALVAR SOLO ───────────────────────────────────────────
@app.post("/ranking/salvar")
def salvar_ranking(body: RankingIn):
    ranking_col.insert_one({
        "_id": str(uuid.uuid4()),
        "jogador_id": body.jogador_id,
        "nome": body.nome,
        "avatar": body.avatar,
        "nivel": body.nivel,
        "tempo": body.tempo,
        "acertos": body.acertos,
        "erros": body.erros,
        "modo": body.modo,
        "data": datetime.utcnow().strftime("%d/%m/%Y")
    })
    return {"ok": True}

# ── RANKING: GLOBAL ────────────────────────────────────────────────
@app.get("/ranking/global")
def ranking_global(nivel: int = 0, modo: str = "todos", limite: int = 50):
    filtro = {}
    if nivel in [1, 2]:
        filtro["nivel"] = nivel
    if modo in ["solo", "batalha"]:
        filtro["modo"] = modo
    docs = list(ranking_col.find(filtro).sort("tempo", 1).limit(limite))
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"ranking": docs, "total": len(docs)}

# ── RANKING: POR NÍVEL ─────────────────────────────────────────────
@app.get("/ranking/nivel/{nivel}")
def ranking_nivel(nivel: int):
    docs = list(ranking_col.find({"nivel": nivel}).sort("tempo", 1).limit(50))
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"ranking": docs, "nivel": nivel}
