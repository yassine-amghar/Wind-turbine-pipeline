import json
import time
from datetime import datetime
import paho.mqtt.client as mqtt
import redis
from pymongo import MongoClient, ASCENDING
from typing import Dict, Optional
import threading


# CONFIGURATION GLOBALE

# MQTT Configuration
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPICS = [
    "wind/turbine/data/T101",
    "wind/turbine/data/T102",
    "wind/turbine/data/T103"
]

# Redis Configuration (Nœud 2)
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_CHANNELS = {
    "T101": "turbine:stream:T101",
    "T102": "turbine:stream:T102",
    "T103": "turbine:stream:T103"
}

# MongoDB Configuration (Nœud 3)
MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB = "wind_farm"
MONGO_COLLECTION = "turbine_data"


# NŒUD 1: DATA COLLECTOR & CLEANER
# Ce nœud écoute MQTT, nettoie les données et les publie vers Redis

class DataCollectorCleaner:
    """Nœud 1: Collecte et nettoyage des données"""
    
    def __init__(self):
        self.mqtt_client = mqtt.Client()
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.setup_mqtt()
        
    def setup_mqtt(self):
        """Configure les callbacks MQTT"""
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        
    def on_connect(self, client, userdata, flags, rc):
        """Callback de connexion MQTT"""
        print(f"[NŒUD 1] Connecté au broker MQTT (code: {rc})")
        for topic in MQTT_TOPICS:
            client.subscribe(topic)
            print(f"[NŒUD 1] Abonné au topic: {topic}")
    
    def clean_data(self, data: Dict) -> Dict:
        """
        Nettoie les données: remplace NaN par None et valide
        """
        cleaned = data.copy()
        
        # Nettoyer les valeurs dans le dict 'data'
        if 'data' in cleaned:
            for key, value in cleaned['data'].items():
                # Vérifier si la valeur est NaN ou invalide
                if value is None or (isinstance(value, float) and (value != value)):  # NaN check
                    cleaned['data'][key] = None
                # Vérifier si c'est une string "NaN"
                elif isinstance(value, str) and value.lower() == 'nan':
                    cleaned['data'][key] = None
        
        # Ajouter un timestamp de traitement
        cleaned['processed_at'] = datetime.now().isoformat()
        
        return cleaned
    
    def on_message(self, client, userdata, msg):
        """Callback de réception de message MQTT"""
        try:
            # Parse le JSON
            raw_data = json.loads(msg.payload.decode())
            turbine_id = raw_data.get('turbine_id')
            
            print(f"[NŒUD 1] Message reçu de {turbine_id}")
            
            # Nettoyer les données
            cleaned_data = self.clean_data(raw_data)
            
            # Publier vers Redis Pub/Sub (Nœud 2)
            redis_channel = REDIS_CHANNELS.get(turbine_id)
            if redis_channel:
                self.redis_client.publish(redis_channel, json.dumps(cleaned_data))
                print(f"[NŒUD 1] Données nettoyées publiées vers Redis: {redis_channel}")
            
        except Exception as e:
            print(f"[NŒUD 1] Erreur: {e}")
    
    def start(self):
        """Démarre le nœud collecteur"""
        print("[NŒUD 1] Démarrage du Data Collector & Cleaner...")
        self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.mqtt_client.loop_forever()


# NŒUD 2: REDIS STREAMING
# Ce nœud gère les streams Redis et distribue les données

class RedisStreamer:
    """Nœud 2: Streaming avec Redis Pub/Sub"""
    
    def __init__(self, turbine_ids):
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.pubsub = self.redis_client.pubsub()
        self.turbine_ids = turbine_ids
        self.mongo_client = MongoClient(MONGO_URI)
        self.db = self.mongo_client[MONGO_DB]
        self.collection = self.db[MONGO_COLLECTION]
        self.setup_indexes()
        
    def setup_indexes(self):
        """Crée les index MongoDB pour optimiser les requêtes"""
        # Index composé: turbine_id + timestamp
        self.collection.create_index([
            ("turbine_id", ASCENDING),
            ("data.# Date and time", ASCENDING)
        ])
        print("[NŒUD 2] Index MongoDB créés")
    
    def subscribe_to_channels(self):
        """S'abonne aux canaux Redis"""
        for turbine_id in self.turbine_ids:
            channel = REDIS_CHANNELS.get(turbine_id)
            if channel:
                self.pubsub.subscribe(channel)
                print(f"[NŒUD 2] Abonné au canal Redis: {channel}")
    
    def process_messages(self):
        """Traite les messages Redis et les envoie vers MongoDB (Nœud 3)"""
        print("[NŒUD 2] En écoute des streams Redis...")
        for message in self.pubsub.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    turbine_id = data.get('turbine_id')
                    
                    print(f"[NŒUD 2] Stream reçu de {turbine_id} → Envoi vers MongoDB")
                    
                    # Envoyer vers le Nœud 3 (MongoDB)
                    self.store_to_mongodb(data)
                    
                except Exception as e:
                    print(f"[NŒUD 2] Erreur: {e}")
    
    def store_to_mongodb(self, data: Dict):
        """Stocke les données dans MongoDB (Nœud 3)"""
        try:
            result = self.collection.insert_one(data)
            print(f"[NŒUD 2→3] Données stockées dans MongoDB: {result.inserted_id}")
        except Exception as e:
            print(f"[NŒUD 2→3] Erreur stockage MongoDB: {e}")
    
    def start(self):
        """Démarre le streaming"""
        print("[NŒUD 2] Démarrage du Redis Streamer...")
        self.subscribe_to_channels()
        self.process_messages()


# ============================================================================
# NŒUD 3: QUERY ENGINE
# Ce nœud exécute les requêtes sur MongoDB
# ============================================================================

class QueryEngine:
    """Nœud 3: Moteur de requêtes MongoDB"""
    
    def __init__(self):
        self.mongo_client = MongoClient(MONGO_URI)
        self.db = self.mongo_client[MONGO_DB]
        self.collection = self.db[MONGO_COLLECTION]
    
    def kpi_1_average_wind_speed(self, turbine_id: Optional[str] = None, time_unit: str = "hour"):
        """
        KPI 1: Vitesse moyenne du vent par éolienne et par unité de temps
        time_unit: 'hour', 'day', 'minute'
        """
        print(f"\n{'='*60}")
        print(f"KPI 1: Vitesse moyenne du vent par éolienne")
        print(f"{'='*60}")
        
        pipeline = []
        
        # Filtrer par turbine si spécifié
        if turbine_id:
            pipeline.append({"$match": {"turbine_id": turbine_id}})
        
        # Filtrer les valeurs null
        pipeline.append({
            "$match": {
                "data.Wind speed (m/s)": {"$ne": None}
            }
        })
        
        # Grouper par turbine et calculer la moyenne
        pipeline.append({
            "$group": {
                "_id": "$turbine_id",
                "avg_wind_speed": {"$avg": "$data.Wind speed (m/s)"},
                "count": {"$sum": 1}
            }
        })
        
        pipeline.append({"$sort": {"_id": 1}})
        
        results = list(self.collection.aggregate(pipeline))
        
        for result in results:
            print(f"Éolienne {result['_id']}: {result['avg_wind_speed']:.2f} m/s (sur {result['count']} mesures)")
        
        return results
    
    def kpi_2_production_efficiency(self, turbine_id: Optional[str] = None):
        """
        KPI 2: Efficacité de production (Power / Wind Speed)
        """
        print(f"\n{'='*60}")
        print(f"KPI 2: Efficacité de production (Power/Wind Speed ratio)")
        print(f"{'='*60}")
        
        pipeline = []
        
        if turbine_id:
            pipeline.append({"$match": {"turbine_id": turbine_id}})
        
        # Filtrer les valeurs null et valides
        pipeline.append({
            "$match": {
                "data.Wind speed (m/s)": {"$ne": None, "$gt": 0},
                "data.Power (kW)": {"$ne": None}
            }
        })
        
        # Calculer l'efficacité
        pipeline.extend([
            {
                "$addFields": {
                    "efficiency": {
                        "$divide": ["$data.Power (kW)", "$data.Wind speed (m/s)"]
                    }
                }
            },
            {
                "$group": {
                    "_id": "$turbine_id",
                    "avg_efficiency": {"$avg": "$efficiency"},
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"_id": 1}}
        ])
        
        results = list(self.collection.aggregate(pipeline))
        
        for result in results:
            print(f"Éolienne {result['_id']}: {result['avg_efficiency']:.2f} kW/(m/s) (sur {result['count']} mesures)")
        
        return results
    
    def kpi_3_daily_energy_production(self, turbine_id: Optional[str] = None):
        """
        KPI 3: Production d'énergie quotidienne par éolienne
        """
        print(f"\n{'='*60}")
        print(f"KPI 3: Production d'énergie quotidienne par éolienne")
        print(f"{'='*60}")
        
        pipeline = []
        
        if turbine_id:
            pipeline.append({"$match": {"turbine_id": turbine_id}})
        
        # Extraire la date et sommer l'énergie
        pipeline.extend([
            {
                "$addFields": {
                    "date": {
                        "$substr": ["$data.# Date and time", 0, 10]
                    }
                }
            },
            {
                "$group": {
                    "_id": {
                        "turbine": "$turbine_id",
                        "date": "$date"
                    },
                    "total_energy": {"$sum": "$data.Energy Export (kWh)"}
                }
            },
            {"$sort": {"_id.date": -1, "_id.turbine": 1}}
        ])
        
        results = list(self.collection.aggregate(pipeline))
        
        for result in results[:10]:  # Afficher les 10 derniers jours
            print(f"{result['_id']['date']} - {result['_id']['turbine']}: {result['total_energy']:.2f} kWh")
        
        return results
    
    def kpi_4_total_energy_exported(self):
        """
        KPI 4: Quantité totale d'énergie exportée depuis le début
        """
        print(f"\n{'='*60}")
        print(f"KPI 4: Quantité totale d'énergie exportée")
        print(f"{'='*60}")
        
        pipeline = [
            {
                "$group": {
                    "_id": "$turbine_id",
                    "total_energy": {"$sum": "$data.Energy Export (kWh)"}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        
        results = list(self.collection.aggregate(pipeline))
        
        total_all = 0
        for result in results:
            print(f"Éolienne {result['_id']}: {result['total_energy']:.2f} kWh")
            total_all += result['total_energy']
        
        print(f"\n{'*'*60}")
        print(f"TOTAL PARC ÉOLIEN: {total_all:.2f} kWh")
        print(f"{'*'*60}")
        
        return results
    
    def run_all_kpis(self):
        """Exécute tous les KPIs"""
        self.kpi_1_average_wind_speed()
        self.kpi_2_production_efficiency()
        self.kpi_3_daily_energy_production()
        self.kpi_4_total_energy_exported()


# ============================================================================
# ORCHESTRATION - DÉMARRAGE DES NŒUDS
# ============================================================================

def start_node_1():
    """Démarre le Nœud 1: Collecteur et Nettoyeur"""
    collector = DataCollectorCleaner()
    collector.start()

def start_node_2():
    """Démarre le Nœud 2: Redis Streamer"""
    streamer = RedisStreamer(['T101', 'T102', 'T103'])
    streamer.start()

def start_query_engine():
    """Démarre le moteur de requêtes"""
    time.sleep(5)  # Attendre que des données soient collectées
    engine = QueryEngine()
    
    while True:
        print("\n" + "="*60)
        print("EXÉCUTION DES KPIs (toutes les 30 secondes)")
        print("="*60)
        engine.run_all_kpis()
        time.sleep(30)


# ============================================================================
# MAIN - POINT D'ENTRÉE
# ============================================================================

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║   WIND TURBINE DATA PIPELINE - ARCHITECTURE DISTRIBUÉE       ║
    ║   3 Nœuds: Collecte → Streaming (Redis) → Stockage (MongoDB) ║
    ╚══════════════════════════════════════════════════════════════╝
    
    INSTRUCTIONS:
    1. Assurez-vous que Mosquitto, Redis et MongoDB sont démarrés
    2. Lancez les 3 générateurs de données (T101, T102, T103)
    3. Lancez ce script
    
    Ce script démarre tous les nœuds en threads séparés.
    """)
    
    # Créer les threads pour chaque nœud
    thread_node_1 = threading.Thread(target=start_node_1, daemon=True)
    thread_node_2 = threading.Thread(target=start_node_2, daemon=True)
    thread_queries = threading.Thread(target=start_query_engine, daemon=True)
    
    # Démarrer les threads
    thread_node_1.start()
    time.sleep(2)  # Laisser le temps au Nœud 1 de se connecter
    thread_node_2.start()
    time.sleep(2)
    thread_queries.start()
    
    # Garder le programme actif
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SYSTÈME] Arrêt du pipeline...")