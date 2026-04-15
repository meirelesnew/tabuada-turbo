const express = require('express');
const cors = require('cors');
const { MongoClient, ObjectId } = require('mongodb');
const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');
require('dotenv').config({ path: '.env.local' });

const app = express();

// Compressão Gzip para arquivos estáticos
const compression = require('compression');
app.use(compression({ threshold: 512, level: 6 }));

// CORS otimizado
app.use(cors({
  origin: ['https://tabuadaturbo.com.br', 'https://www.tabuadaturbo.com.br'],
  methods: ['GET', 'POST'],
  credentials: true
}));

app.use(express.json({ limit: '1mb' }));

// Headers de segurança e performance
app.use((req, res, next) => {
  res.set('X-Content-Type-Options', 'nosniff');
  res.set('X-Frame-Options', 'DENY');
  res.set('X-XSS-Protection', '1; mode=block');
  res.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  res.set('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
  next();
});

// Cache otimizado para estáticos
app.use(express.static(path.join(__dirname), {
  maxAge: '7d',
  etag: true,
  lastModified: true,
  immutable: process.env.NODE_ENV === 'production'
}));

// Servir index.html com cache curto (HTML dinâmico)
app.get('*', (req, res, next) => {
  if (req.path.endsWith('.html') || req.path === '/') {
    res.set('Cache-Control', 'public, max-age=0, must-revalidate');
    res.set('Service-Worker-Allowed', '/');
  }
  next();
});

// Configuração do MongoDB
let mongoClient = null;
let db = null;
let isDbConnected = false;

const MONGO_URL = process.env.MONGO_URL || 'mongodb+srv://Admin:oAgtNf8ujb6sHKew@tabuada2026.cjzpxgk.mongodb.net/?retryWrites=true&w=majority&appName=tabuada2026';

async function connectMongo() {
  try {
    mongoClient = new MongoClient(MONGO_URL, {
      serverSelectionTimeoutMS: 10000,
      connectTimeoutMS: 10000,
      retryWrites: true,
      w: 'majority'
    });
    
    console.log('📡 Conectando ao MongoDB...');
    await mongoClient.connect();
    
    db = mongoClient.db('tabuada2026');
    isDbConnected = true;
    console.log('✅ MongoDB conectado com sucesso');
    
    // Criar índice TTL para salas
    try {
      await db.collection('salas').createIndex(
        { 'expira_em': 1 },
        { expireAfterSeconds: 0 }
      );
      console.log('✅ Índice TTL criado');
    } catch (e) {
      console.log('⚠️ Índice TTL pode já existir:', e.message);
    }
  } catch (err) {
    console.error('❌ Erro ao conectar MongoDB:', err.message);
    console.log('⚠️ Funcionando em modo degradado (sem persistência)');
    isDbConnected = false;
    // Não relançar erro - deixar servidor subir em modo offline
  }
}

// Middleware para cache
app.use((req, res, next) => {
  res.set('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0');
  res.set('Pragma', 'no-cache');
  res.set('Expires', '0');
  next();
});

// ═══════════════════════════════════════════════════════════════
// ROTAS
// ═══════════════════════════════════════════════════════════════

// Health check
app.get('/health', (req, res) => {
  res.json({ status: isDbConnected ? 'ok' : 'degraded', db: isDbConnected ? 'conectado' : 'offline' });
});

app.get('/ping', (req, res) => {
  res.json({ status: 'ok', time: new Date().toISOString() });
});

// Salvar jogador
app.post('/jogador/salvar', async (req, res) => {
  const { nome, avatar } = req.body;
  const jogadorId = uuidv4();
  
  if (isDbConnected && db) {
    await db.collection('jogadores').replaceOne(
      { _id: jogadorId },
      { _id: jogadorId, nome, avatar, criado_em: new Date() },
      { upsert: true }
    );
  }
  
  res.json({ jogador_id: jogadorId, nome, avatar });
});

// ═══════════════════════════════════════════════════════════════
// BATALHA
// ═══════════════════════════════════════════════════════════════

function gerarCodigo() {
  const letras = Math.random().toString(36).substring(2, 7).toUpperCase();
  const nums = Math.floor(Math.random() * 900 + 100);
  return `${letras}-${nums}`;
}

app.post('/batalha/criar', async (req, res) => {
  if (!isDbConnected || !db) {
    return res.status(503).json({ detail: 'Serviço indisponível' });
  }
  
  const { jogador_id, nome, avatar, nivel } = req.body;
  let codigo = gerarCodigo();
  
  // Verificar código único
  while (await db.collection('salas').findOne({ codigo, status: { $ne: 'finalizada' } })) {
    codigo = gerarCodigo();
  }
  
  const sala = {
    _id: uuidv4(),
    codigo,
    nivel: parseInt(nivel),
    status: 'aguardando',
    criado_em: new Date(),
    expira_em: new Date(Date.now() + 30 * 60 * 1000),
    jogadores: [{
      id: jogador_id,
      nome,
      avatar,
      tempo: null,
      acertos: null,
      erros: null,
      finalizado: false,
      entrou_em: new Date()
    }]
  };
  
  await db.collection('salas').insertOne(sala);
  res.json({ codigo, nivel: sala.nivel, status: 'aguardando' });
});

app.post('/batalha/entrar', async (req, res) => {
  if (!isDbConnected || !db) {
    return res.status(503).json({ detail: 'Serviço indisponível' });
  }
  
  const { codigo, jogador_id, nome, avatar } = req.body;
  const sala = await db.collection('salas').findOne({ codigo: codigo.toUpperCase() });
  
  if (!sala) return res.status(404).json({ detail: 'Sala não encontrada' });
  if (sala.status === 'finalizada') return res.status(400).json({ detail: 'Sala finalizada' });
  if (sala.status === 'em_jogo') return res.status(400).json({ detail: 'Partida iniciada' });
  
  const idsNaSala = sala.jogadores.map(j => j.id);
  if (!idsNaSala.includes(jogador_id)) {
    await db.collection('salas').updateOne(
      { codigo: codigo.toUpperCase() },
      { $push: { jogadores: { id: jogador_id, nome, avatar, tempo: null, acertos: null, erros: null, finalized: false, entrou_em: new Date() } } }
    );
  }
  
  const salaAtt = await db.collection('salas').findOne({ codigo: codigo.toUpperCase() });
  res.json({ codigo: salaAtt.codigo, nivel: salaAtt.nivel, status: salaAtt.status, jogadores: salaAtt.jogadores });
});

app.get('/batalha/:codigo', async (req, res) => {
  if (!isDbConnected || !db) {
    return res.status(503).json({ detail: 'Serviço indisponível' });
  }
  
  const sala = await db.collection('salas').findOne({ codigo: req.params.codigo.toUpperCase() });
  if (!sala) return res.status(404).json({ detail: 'Sala não encontrada' });
  res.json({ codigo: sala.codigo, nivel: sala.nivel, status: sala.status, jogadores: sala.jogadores });
});

app.post('/batalha/:codigo/iniciar', async (req, res) => {
  if (!isDbConnected || !db) {
    return res.status(503).json({ detail: 'Serviço indisponível' });
  }
  
  const sala = await db.collection('salas').findOne({ codigo: req.params.codigo.toUpperCase() });
  if (!sala) return res.status(404).json({ detail: 'Sala não encontrada' });
  if (sala.jogadores.length < 2) return res.status(400).json({ detail: 'Aguardando jogadores' });
  
  await db.collection('salas').updateOne(
    { codigo: req.params.codigo.toUpperCase() },
    { $set: { status: 'em_jogo', iniciado_em: new Date() } }
  );
  res.json({ status: 'em_jogo' });
});

app.post('/batalha/finalizar', async (req, res) => {
  if (!isDbConnected || !db) {
    return res.status(503).json({ detail: 'Serviço indisponível' });
  }
  
  const { codigo, jogador_id, tempo, acertos, erros } = req.body;
  const sala = await db.collection('salas').findOne({ codigo: codigo.toUpperCase() });
  if (!sala) return res.status(404).json({ detail: 'Sala não encontrada' });
  
  // Atualizar jogador
  await db.collection('salas').updateOne(
    { codigo: codigo.toUpperCase(), 'jogadores.id': jogador_id },
    { $set: { 'jogadores.$.tempo': tempo, 'jogadores.$.acertos': acertos, 'jogadores.$.erros': erros, 'jogadores.$.finalizado': true } }
  );
  
  const salaAtt = await db.collection('salas').findOne({ codigo: codigo.toUpperCase() });
  const todosProntos = salaAtt.jogadores.every(j => j.finalizado);
  
  if (todosProntos) {
    await db.collection('salas').updateOne({ codigo: codigo.toUpperCase() }, { $set: { status: 'finalizada' } });
  }
  
  // Salvar no ranking
  const jogadorInfo = salaAtt.jogadores.find(j => j.id === jogador_id);
  await db.collection('ranking').insertOne({
    _id: uuidv4(),
    jogador_id,
    nome: jogadorInfo?.nome || '?',
    avatar: jogadorInfo?.avatar || '🦁',
    nivel: salaAtt.nivel,
    tempo,
    acertos,
    erros,
    modo: 'batalha',
    data: new Date().toLocaleDateString('pt-BR')
  });
  
  res.json({ status: todosProntos ? 'finalizada' : salaAtt.status, jogadores: salaAtt.jogadores });
});

// ═══════════════════════════════════════════════════════════════
// RANKING
// ═══════════════════════════════════════════════════════════════

app.post('/ranking/salvar', async (req, res) => {
  if (!isDbConnected || !db) {
    return res.json({ ok: false, offline: true });
  }
  
  const { jogador_id, nome, avatar, nivel, tempo, acertos, erros, modo } = req.body;
  await db.collection('ranking').insertOne({
    _id: uuidv4(),
    jogador_id,
    nome,
    avatar,
    nivel: parseInt(nivel),
    tempo: parseInt(tempo),
    acertos: parseInt(acertos),
    erros: parseInt(erros),
    modo,
    data: new Date().toLocaleDateString('pt-BR')
  });
  res.json({ ok: true });
});

app.get('/ranking/global', async (req, res) => {
  if (!isDbConnected || !db) {
    return res.json({ ranking: [], total: 0, offline: true });
  }
  
  const { nivel, modo, limite = 50 } = req.query;
  const match = {};
  if (nivel) match.nivel = parseInt(nivel);
  if (modo && modo !== 'todos') match.modo = modo;
  
  const pipeline = [
    { $match: match },
    { $sort: { tempo: 1 } },
    { $group: {
      _id: '$jogador_id',
      nome: { $first: '$nome' },
      avatar: { $first: '$avatar' },
      nivel: { $first: '$nivel' },
      tempo: { $min: '$tempo' },
      acertos: { $first: '$acertos' },
      erros: { $first: '$erros' },
      modo: { $first: '$modo' },
      data: { $first: '$data' }
    }},
    { $sort: { tempo: 1 } },
    { $limit: parseInt(limite) }
  ];
  
  const docs = await db.collection('ranking').aggregate(pipeline).toArray();
  const ranking = docs.map(d => ({ ...d, jogador_id: d._id, _id: d._id }));
  res.json({ ranking, total: ranking.length });
});

app.get('/ranking/nivel/:nivel', async (req, res) => {
  if (!isDbConnected || !db) {
    return res.json({ ranking: [], nivel: parseInt(req.params.nivel), offline: true });
  }
  
  const nivel = parseInt(req.params.nivel);
  const docs = await db.collection('ranking')
    .find({ nivel })
    .sort({ tempo: 1 })
    .limit(50)
    .toArray();
  
  res.json({ ranking: docs.map(d => ({ ...d, _id: d._id.toString() })), nivel });
});

app.get('/ranking/posicao', async (req, res) => {
  if (!isDbConnected || !db) {
    return res.json({ posicao: 0, offline: true });
  }
  
  const { tempo, nivel } = req.query;
  const result = await db.collection('ranking').aggregate([
    { $match: { nivel: parseInt(nivel) } },
    { $group: { _id: '$jogador_id', melhor: { $min: '$tempo' } } },
    { $match: { melhor: { $lt: parseInt(tempo) } } },
    { $count: 'total' }
  ]).toArray();
  
  const qtd = result[0]?.total || 0;
  res.json({ posicao: qtd + 1 });
});

// ═══════════════════════════════════════════════════════════════
// INICIAR SERVIDOR
// ═══════════════════════════════════════════════════════════════

const PORT = process.env.PORT || 10000;

// ✅ CORREÇÃO PDCA: Inicializar server APÓS MongoDB estar pronto
async function iniciarServidor() {
  try {
    // Aguardar conexão MongoDB
    await connectMongo();
    
    // SÓ DEPOIS iniciar server
    app.listen(PORT, '0.0.0.0', () => {
      console.log(`🚀 Tabuada Turbo API rodando na porta ${PORT}`);
      console.log(`✅ Database: ${isDbConnected ? 'CONECTADO' : 'MODO OFFLINE'}`);
    });
  } catch (err) {
    console.error('❌ Erro ao iniciar servidor:', err);
    process.exit(1);
  }
}

// Iniciar servidor
iniciarServidor();

module.exports = app;