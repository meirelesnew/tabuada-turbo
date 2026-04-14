from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pydantic import BaseModel
from datetime import datetime, timedelta
import random, string, uuid, os

MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://Admin:Bekg9u8pe5SPHiQg@tabuada2026.cjzpxgk.mongodb.net/?retryWrites=true&w=majority&appName=tabuada2026")

client = db = jogadores_col = salas_col = ranking_col = None

def conectar_mongo():
    global client, db, jogadores_col, salas_col, ranking_col
    print(f"[MONGO] Iniciando conexao...")
    try:
        client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=10000)
        client.admin.command("ping")
        db = client["tabuada2026"]
        jogadores_col = db["jogadores"]
        salas_col     = db["salas"]
        ranking_col   = db["ranking"]
        print("[MONGO] Conectado com sucesso!")
        return True
    except Exception as e:
        print(f"[MONGO] ERRO: {e}")
        return False

conectar_mongo()

app = FastAPI(title="Tabuada Turbo API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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

def gerar_codigo():
    return ''.join(random.choices(string.ascii_uppercase, k=5)) + '-' + ''.join(random.choices(string.digits, k=3))

def check_db():
    if db is None:
        raise HTTPException(status_code=503, detail="Banco indisponivel")

@app.get("/")
def root():
    return {"status": "ok", "app": "Tabuada Turbo API v2.0"}

@app.get("/health")
def health():
    try:
        if client is None:
            return {"status": "erro", "db": "desconectado", "msg": "client is None"}
        client.admin.command("ping")
        total = ranking_col.count_documents({}) if ranking_col is not None else 0
        return {"status": "ok", "db": "conectado", "ranking_total": total}
    except Exception as e:
        return {"status": "erro", "db": str(e)}

@app.post("/jogador/salvar")
def salvar_jogador(body: JogadorIn):
    check_db()
    jid = str(uuid.uuid4())
    jogadores_col.replace_one({"_id": jid},
        {"_id": jid, "nome": body.nome, "avatar": body.avatar,
         "criado_em": datetime.utcnow().isoformat()}, upsert=True)
    return {"jogador_id": jid, "nome": body.nome, "avatar": body.avatar}

@app.post("/ranking/salvar")
def salvar_ranking(body: RankingIn):
    check_db()
    print(f"[RANKING] Salvando {body.nome} nivel={body.nivel} tempo={body.tempo}")
    ranking_col.insert_one({
        "_id": str(uuid.uuid4()),
        "jogador_id": body.jogador_id,
        "nome": body.nome, "avatar": body.avatar,
        "nivel": body.nivel, "tempo": body.tempo,
        "acertos": body.acertos, "erros": body.erros,
        "modo": body.modo,
        "data": datetime.utcnow().strftime("%d/%m/%Y")
    })
    print(f"[RANKING] Salvo com sucesso!")
    return {"ok": True}

@app.get("/ranking/global")
def ranking_global(nivel: int = 0, modo: str = "todos", limite: int = 50):
    check_db()
    filtro = {}
    if nivel in [1, 2]: filtro["nivel"] = nivel
    if modo in ["solo", "batalha"]: filtro["modo"] = modo
    docs = list(ranking_col.find(filtro).sort("tempo", 1).limit(limite))
    for d in docs: d["_id"] = str(d["_id"])
    print(f"[RANKING] Retornando {len(docs)} registros")
    return {"ranking": docs, "total": len(docs)}

@app.get("/ranking/nivel/{nivel}")
def ranking_nivel(nivel: int):
    check_db()
    docs = list(ranking_col.find({"nivel": nivel}).sort("tempo", 1).limit(50))
    for d in docs: d["_id"] = str(d["_id"])
    return {"ranking": docs, "nivel": nivel}

@app.post("/batalha/criar")
def criar_sala(body: CriarSalaIn):
    check_db()
    codigo = gerar_codigo()
    while salas_col.find_one({"codigo": codigo, "status": {"$ne": "finalizada"}}):
        codigo = gerar_codigo()
    sala = {
        "_id": str(uuid.uuid4()), "codigo": codigo,
        "nivel": body.nivel, "status": "aguardando",
        "criado_em": datetime.utcnow().isoformat(),
        "expira_em": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
        "jogadores": [{"id": body.jogador_id, "nome": body.nome, "avatar": body.avatar,
            "tempo": None, "acertos": None, "erros": None, "finalizado": False,
            "entrou_em": datetime.utcnow().isoformat()}]
    }
    salas_col.insert_one(sala)
    return {"codigo": codigo, "nivel": body.nivel, "status": "aguardando"}

@app.post("/batalha/entrar")
def entrar_sala(body: EntrarSalaIn):
    check_db()
    sala = salas_col.find_one({"codigo": body.codigo.upper()})
    if not sala: raise HTTPException(404, "Sala nao encontrada")
    if sala["status"] == "finalizada": raise HTTPException(400, "Sala finalizada")
    if sala["status"] == "em_jogo": raise HTTPException(400, "Partida iniciada")
    if body.jogador_id not in [j["id"] for j in sala["jogadores"]]:
        salas_col.update_one({"codigo": body.codigo.upper()},
            {"$push": {"jogadores": {"id": body.jogador_id, "nome": body.nome,
                "avatar": body.avatar, "tempo": None, "acertos": None, "erros": None,
                "finalizado": False, "entrou_em": datetime.utcnow().isoformat()}}})
    sala_att = salas_col.find_one({"codigo": body.codigo.upper()})
    return {"codigo": sala_att["codigo"], "nivel": sala_att["nivel"],
            "status": sala_att["status"], "jogadores": sala_att["jogadores"]}

@app.get("/batalha/{codigo}")
def status_sala(codigo: str):
    check_db()
    sala = salas_col.find_one({"codigo": codigo.upper()})
    if not sala: raise HTTPException(404, "Sala nao encontrada")
    return {"codigo": sala["codigo"], "nivel": sala["nivel"],
            "status": sala["status"], "jogadores": sala["jogadores"]}

@app.post("/batalha/{codigo}/iniciar")
def iniciar_sala(codigo: str):
    check_db()
    sala = salas_col.find_one({"codigo": codigo.upper()})
    if not sala: raise HTTPException(404, "Sala nao encontrada")
    if len(sala["jogadores"]) < 2: raise HTTPException(400, "Aguardando jogadores")
    salas_col.update_one({"codigo": codigo.upper()},
        {"$set": {"status": "em_jogo", "iniciado_em": datetime.utcnow().isoformat()}})
    return {"status": "em_jogo"}

@app.post("/batalha/finalizar")
def finalizar_jogador(body: FinalizarIn):
    check_db()
    sala = salas_col.find_one({"codigo": body.codigo.upper()})
    if not sala: raise HTTPException(404, "Sala nao encontrada")
    salas_col.update_one(
        {"codigo": body.codigo.upper(), "jogadores.id": body.jogador_id},
        {"$set": {"jogadores.$.tempo": body.tempo, "jogadores.$.acertos": body.acertos,
                  "jogadores.$.erros": body.erros, "jogadores.$.finalizado": True}})
    sala_att = salas_col.find_one({"codigo": body.codigo.upper()})
    if all(j["finalizado"] for j in sala_att["jogadores"]):
        salas_col.update_one({"codigo": body.codigo.upper()},
                             {"$set": {"status": "finalizada"}})
    j_info = next((j for j in sala_att["jogadores"] if j["id"] == body.jogador_id), {})
    ranking_col.insert_one({
        "_id": str(uuid.uuid4()), "jogador_id": body.jogador_id,
        "nome": j_info.get("nome", "?"), "avatar": j_info.get("avatar", "?"),
        "nivel": sala_att["nivel"], "tempo": body.tempo,
        "acertos": body.acertos, "erros": body.erros,
        "modo": "batalha", "data": datetime.utcnow().strftime("%d/%m/%Y")})
    sala_final = salas_col.find_one({"codigo": body.codigo.upper()})
    return {"status": sala_final["status"], "jogadores": sala_final["jogadores"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000)
