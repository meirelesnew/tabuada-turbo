from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient
from pydantic import BaseModel
from datetime import datetime, timedelta
import random, string, uuid, os

# ✅ Fix 1: Credencial via variável de ambiente do Render
MONGO_URL = os.environ.get("MONGO_URL")
if not MONGO_URL:
    # Se você estiver testando localmente e ainda não definiu a variável, 
    # pode colocar a string aqui temporariamente, mas no Render use o painel.
    print("AVISO: MONGO_URL não definida. O servidor pode falhar ao conectar.")

# ✅ Fix 2: Token admin para limpeza de ranking
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "tt_admin_2026")

client = db = jogadores_col = salas_col = ranking_col = None

def conectar_mongo():
    global client, db, jogadores_col, salas_col, ranking_col
    if not MONGO_URL: return False
    print("[MONGO] Iniciando conexao...")
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

app = FastAPI(title="Tabuada Turbo API", version="2.1.0")

# ✅ Configuração de CORS (Permite que seu site .com.br fale com o Render)
app.add_middleware(CORSMiddleware, 
    allow_origins=["*"],
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"])

# ─── Entrega do Frontend (IMPORTANTE para tirar o 'Not Found') ──────────────

# Rota para abrir o jogo na página inicial
@app.get("/")
async def root():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return JSONResponse({"status": "ok", "msg": "API Online, mas index.html não encontrado na raiz."})

# ─── Models ───────────────────────────────────────────────────────────────────

class JogadorIn(BaseModel):
    nome: str
    avatar: str
    jogador_id: str = ""

class RankingIn(BaseModel):
    jogador_id: str
    nome: str
    avatar: str
    nivel: int
    tempo: int
    acertos: int
    erros: int
    modo: str

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

# ─── Helpers ──────────────────────────────────────────────────────────────────

def check_db():
    if db is None:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível")

def check_admin(token: str):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Token inválido")

# ─── Rotas de Saúde e Diagnóstico ─────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok", "db": "conectado", "timestamp": datetime.now().isoformat()}
    except:
        return {"status": "erro", "db": "desconectado"}

# ─── Jogador ──────────────────────────────────────────────────────────────────

@app.post("/jogador/salvar")
def salvar_jogador(body: JogadorIn):
    check_db()
    jid = body.jogador_id if body.jogador_id else str(uuid.uuid4())
    jogadores_col.update_one(
        {"_id": jid},
        {"$set": {
            "nome": body.nome,
            "avatar": body.avatar,
            "atualizado_em": datetime.utcnow().isoformat()
        }, "$setOnInsert": {
            "criado_em": datetime.utcnow().isoformat()
        }},
        upsert=True
    )
    return {"jogador_id": jid, "nome": body.nome, "avatar": body.avatar}

# ─── Ranking ──────────────────────────────────────────────────────────────────

@app.post("/ranking/salvar")
def salvar_ranking(body: RankingIn):
    check_db()
    ranking_col.insert_one({
        "_id": str(uuid.uuid4()),
        "jogador_id": body.jogador_id,
        "nome": body.nome,
        "avatar": body.avatar,
        "nivel": int(body.nivel),
        "tempo": int(body.tempo),
        "acertos": int(body.acertos),
        "erros": int(body.erros),
        "modo": body.modo,
        "data": datetime.utcnow().strftime("%d/%m/%Y"),
        "enviado_em": datetime.utcnow()
    })
    return {"ok": True}

@app.get("/ranking/global")
def ranking_global(nivel: int = 0, modo: str = "todos", limite: int = 50):
    check_db()
    filtro = {}
    if nivel in [1, 2]: filtro["nivel"] = nivel
    if modo in ["solo", "batalha"]: filtro["modo"] = modo
    
    # Pipeline de agregação para consolidar o melhor tempo de cada jogador
    pipeline = [
        {"$match": filtro},
        # Garante que o tempo seja número
        {"$match": {"tempo": {"$type": ["int", "long", "double", "decimal"]}}},
        # Ordena por tempo (menor primeiro) e data de envio
        {"$sort": {"tempo": 1, "enviado_em": 1}},
        # Agrupa pelo jogador_id para pegar apenas a melhor marca de cada um
        {"$group": {
            "_id": "$jogador_id",
            "nome": {"$first": "$nome"},
            "avatar": {"$first": "$avatar"},
            "nivel": {"$first": "$nivel"},
            "tempo": {"$first": "$tempo"},
            "acertos": {"$first": "$acertos"},
            "erros": {"$first": "$erros"},
            "modo": {"$first": "$modo"},
            "data": {"$first": "$data"}
        }},
        # Ordena o ranking final consolidado
        {"$sort": {"tempo": 1}},
        {"$limit": limite}
    ]
    
    docs = list(ranking_col.aggregate(pipeline))
    for d in docs:
        # Renomear _id para jogador_id e converter para string se necessário
        d["jogador_id"] = str(d["_id"])
        if "_id" in d: del d["_id"]
        
    return {"ranking": docs}

# ─── Admin (Limpeza) ─────────────────────────────────────────────────────────

@app.get("/admin/limpar-invalidos")
def limpar_invalidos(token: str = Query(default="")):
    check_admin(token)
    check_db()
    # Remove registros onde o tempo foi salvo como texto por erro de versão antiga
    res = ranking_col.delete_many({"tempo": {"$type": "string"}})
    return {"removidos": res.deleted_count}

# ─── Batalhas Multijogador (Resumo) ───────────────────────────────────────────

@app.post("/batalha/criar")
def criar_sala(body: CriarSalaIn):
    check_db()
    codigo = ''.join(random.choices(string.ascii_uppercase, k=5))
    sala = {
        "_id": str(uuid.uuid4()),
        "codigo": codigo,
        "nivel": body.nivel,
        "status": "aguardando",
        "jogadores": [{"id": body.jogador_id, "nome": body.nome, "avatar": body.avatar, "finalizado": False}]
    }
    salas_col.insert_one(sala)
    return {"codigo": codigo}

# ... (Mantenha as outras rotas de batalha que você já tem) ...

if __name__ == "__main__":
    import uvicorn
    # Porta 10000 exigida pelo Render
    uvicorn.run(app, host="0.0.0.0", port=10000)
    
