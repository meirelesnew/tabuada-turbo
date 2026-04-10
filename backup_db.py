import os
import json
from datetime import datetime
from pymongo import MongoClient

def run_backup():
    # URL do MongoDB (mesma usada no app)
    MONGO_URL_DIRETA = "mongodb+srv://Admin:oAgtNf8ujb6sHKew@tabuada2026.cjzpxgk.mongodb.net/?retryWrites=true&w=majority&appName=tabuada2026"
    MONGO_URL = os.environ.get("MONGO_URL", MONGO_URL_DIRETA)
    
    # Criar pasta de backup com data
    data_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_dir = f"backups/backup_{data_str}"
    os.makedirs(backup_dir, exist_ok=True)
    
    print(f"🚀 Iniciando backup em: {backup_dir}")
    
    try:
        client = MongoClient(MONGO_URL)
        db = client["tabuada2026"]
        
        collections = ["jogadores", "salas", "ranking"]
        
        for coll_name in collections:
            print(f"📦 Exportando: {coll_name}...")
            collection = db[coll_name]
            cursor = collection.find({})
            
            data = []
            for doc in cursor:
                # Converter ObjectId e datetime para string se necessário
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
                if "expira_em" in doc and isinstance(doc["expira_em"], datetime):
                    doc["expira_em"] = doc["expira_em"].isoformat()
                data.append(doc)
            
            # Salvar em JSON
            file_path = os.path.join(backup_dir, f"{coll_name}.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            print(f"✅ {coll_name} salvo com sucesso! ({len(data)} documentos)")
            
        print("\n✨ Backup concluído com sucesso!")
        print(f"📂 Arquivos disponíveis em: {os.path.abspath(backup_dir)}")
        
    except Exception as e:
        print(f"❌ Erro crítico durante o backup: {e}")

if __name__ == "__main__":
    run_backup()
