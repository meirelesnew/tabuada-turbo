from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import random
import string
import uuid
import os
import hashlib
import jwt

app = FastAPI()

# Estes serão inicializados no startup para evitar lentidão no boot da Render
client = None
db = None
jogadores_col = None
salas_col = None
ranking_col = None
usuarios_col = None

@app.on_event("startup")
def startup_db_client():
    global client, db, jogadores_col, salas_col, ranking_col, usuarios_col
    
    MONGO_URL_DIRETA = "mongodb+srv://Admin:oAgtNf8ujb6sHKew@tabuada2026.cjzpxgk.mongodb.net/?retryWrites=true&w=majority&appName=tabuada2026"
    MONGO_URL = os.environ.get("MONGO_URL", MONGO_URL_DIRETA)

    if MONGO_URL:
        try:
            print(f"📡 Tentando conectar ao MongoDB no startup... (Timeout: 5s)")
            client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
            client.admin.command("ping")
            db = client["tabuada2026"]
            
            jogadores_col = db["jogadores"]
            salas_col     = db["salas"]
            ranking_col   = db["ranking"]
            usuarios_col  = db["usuarios"]
            
            print("✅ MongoDB conectado com sucesso")
            
            # Criar índice TTL nas salas
            try:
                salas_col.create_index("expira_em", expireAfterSeconds=0)
                print("✅ Índice TTL criado com sucesso em 'salas_col'")
            except Exception as e:
                print(f"⚠️ Erro ao criar índice TTL: {e}")
                
        except Exception as e:
            print(f"⚠️ Erro ao conectar MongoDB no startup: {e}")
            print("⚠️ O API continuará rodando em modo limitado (sem banco).")
    else:
        print("⚠️ MONGO_URL não configurada - API funcionará em modo limitado")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Headers para evitar cache do Cloudflare
@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ── MODELS ──────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    email: str
    senha: str

class RegistrarIn(BaseModel):
    nome: str
    email: str
    senha: str

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

import os

# Get base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── HEALTH ──────────────────────────────────────────────────────────
@app.get("/health")
def health():
    if client is None or db is None:
        return {"status": "ok", "db": "offline"}
    try:
        client.admin.command("ping")
        return {"status": "ok", "db": "conectado"}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

@app.get("/ping")
def ping():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

@app.get("/")
def root():
    index_path = os.path.join(BASE_DIR, "index.html")
    print(f"Looking for index.html at: {index_path}")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"status": "ok", "app": "Tabuada Turbo API v1.0"}

@app.get("/{file_path:path}")
async def serve_static(file_path: str):
    allowed_files = ['manifest.json', 'sw.js', 'robots.txt', 'sitemap.xml', 'favicon.ico', 'og-image.png']
    if file_path in allowed_files:
        file_path_static = os.path.join(BASE_DIR, file_path)
        if os.path.exists(file_path_static):
            return FileResponse(file_path_static)
    return {"error": "Not found"}, 404

# ── AUTH: LOGIN ─────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("JWT_SECRET", "tabuada_turbo_2026_secreto")
ALGORITHM = "HS256"

def criar_token(usuario_id: str, nome: str, email: str) -> str:
    return jwt.encode(
        {"sub": usuario_id, "nome": nome, "email": email},
        SECRET_KEY,
        algorithm=ALGORITHM
    )

def verificar_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except:
        return None

@app.post("/auth/login")
def login(body: LoginIn):
    if not usuarios_col:
        return {"erro": "Serviço indisponível"}, 503
    
    usuario = usuarios_col.find_one({"email": body.email})
    senha_hash = hashlib.sha256(body.senha.encode()).hexdigest()
    if not usuario or senha_hash != usuario.get("senha"):
        return {"erro": "Credenciais incorretas"}
    
    token = criar_token(str(usuario["_id"]), usuario["nome"], usuario["email"])
    return {
        "token": token,
        "usuario": {
            "nome": usuario["nome"],
            "email": usuario["email"],
            "avatar": usuario.get("avatar", "🦁")
        }
    }

@app.post("/auth/registrar")
def registrar(body: RegistrarIn):
    if not usuarios_col:
        return {"erro": "Serviço indisponível"}, 503
    
    if usuarios_col.find_one({"email": body.email}):
        return {"erro": "Email já cadastrado"}
    
    uid = str(uuid.uuid4())
    senha_hash = hashlib.sha256(body.senha.encode()).hexdigest()
    doc = {
        "_id": uid,
        "nome": body.nome,
        "email": body.email,
        "senha": senha_hash,
        "avatar": "🦁",
        "criado_em": datetime.utcnow().isoformat()
    }
    usuarios_col.insert_one(doc)
    
    token = criar_token(uid, body.nome, body.email)
    return {
        "token": token,
        "usuario": {
            "nome": body.nome,
            "email": body.email,
            "avatar": "🦁"
        }
    }

@app.get("/auth/me")
def quem_sou(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return {"erro": "Não autorizado"}, 401
    
    token = authorization.replace("Bearer ", "")
    dados = verificar_token(token)
    if not dados:
        return {"erro": "Token inválido"}, 401
    
    return {
        "nome": dados.get("nome"),
        "email": dados.get("email")
    }

# ── JOGADOR ─────────────────────────────────────────────────────────
@app.post("/jogador/salvar")
def salvar_jogador(body: JogadorIn):
    if not jogadores_col:
        return {"jogador_id": str(uuid.uuid4()), "nome": body.nome, "avatar": body.avatar}
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
    if not salas_col:
        raise HTTPException(status_code=503, detail="Serviço temporariamente indisponível")
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
        "expira_em": expira_em,  # Deve ser datetime, não string, para TTL funcionar
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
    if not salas_col:
        raise HTTPException(status_code=503, detail="Serviço indisponível")
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

# ── RANKING: GLOBAL (melhor score por jogador) ──────────────────────
@app.get("/ranking/global")
def ranking_global(nivel: int = 0, modo: str = "todos", limite: int = 50):
    """
    Retorna o melhor tempo de cada jogador (deduplicado por jogador_id).
    Filtros opcionais: nivel (1|2), modo (solo|batalha).
    """
    match = {}
    if nivel in [1, 2]:
        match["nivel"] = nivel
    if modo in ["solo", "batalha"]:
        match["modo"] = modo

    pipeline = []
    if match:
        pipeline.append({"$match": match})
    pipeline += [
        # Agrupa por jogador e pega o menor tempo
        {"$sort": {"tempo": 1}},
        {"$group": {
            "_id": "$jogador_id",
            "nome":    {"$first": "$nome"},
            "avatar":  {"$first": "$avatar"},
            "nivel":   {"$first": "$nivel"},
            "tempo":   {"$min": "$tempo"},
            "acertos": {"$first": "$acertos"},
            "erros":   {"$first": "$erros"},
            "modo":    {"$first": "$modo"},
            "data":    {"$first": "$data"}
        }},
        {"$sort": {"tempo": 1}},
        {"$limit": limite}
    ]

    docs = list(ranking_col.aggregate(pipeline))
    for d in docs:
        d["jogador_id"] = str(d.pop("_id"))
    return {"ranking": docs, "total": len(docs)}

# ── RANKING: POSIÇÃO GLOBAL ─────────────────────────────────────────
@app.get("/ranking/posicao")
def ranking_posicao(tempo: int, nivel: int):
    """Retorna a posição do jogador considerando apenas o melhor tempo por jogador."""
    # Agrupa por jogador, pega o melhor tempo, conta quantos têm tempo menor
    pipeline = [
        {"$match": {"nivel": nivel}},
        {"$group": {"_id": "$jogador_id", "melhor": {"$min": "$tempo"}}},
        {"$match": {"melhor": {"$lt": tempo}}},
        {"$count": "total"}
    ]
    result = list(ranking_col.aggregate(pipeline))
    qtd = result[0]["total"] if result else 0
    return {"posicao": qtd + 1}

# ── RANKING: POR NÍVEL ─────────────────────────────────────────────
@app.get("/ranking/nivel/{nivel}")
def ranking_nivel(nivel: int):
    docs = list(ranking_col.find({"nivel": nivel}).sort("tempo", 1).limit(50))
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"ranking": docs, "nivel": nivel}

@app.get("/admin/backup")
def admin_backup(token: str):
    # Token simples para proteção (pode ser movido para env var depois)
    SECRET_TOKEN = os.environ.get("ADMIN_TOKEN", "tabuada_turbo_secret_2026")
    if token != SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    if client is None or db is None:
        raise HTTPException(status_code=503, detail="Banco offline")
        
    backup_data = {}
    collections = ["jogadores", "salas", "ranking"]
    for coll_name in collections:
        cursor = db[coll_name].find({})
        data = []
        for doc in cursor:
            if "_id" in doc: doc["_id"] = str(doc["_id"])
            if "expira_em" in doc and isinstance(doc["expira_em"], datetime):
                doc["expira_em"] = doc["expira_em"].isoformat()
            data.append(doc)
        backup_data[coll_name] = data
        
    return {
        "data_backup": datetime.utcnow().isoformat(),
        "total_colecoes": len(backup_data),
        "backup": backup_data
    }

if __name__ == "__main__":
    import uvicorn
    # Render fornece a porta via variável de ambiente PORT
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
