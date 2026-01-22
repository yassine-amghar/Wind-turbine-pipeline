# Wind-turbine-pipeline

┌─────────────────────────────────────────────────────────────┐
│                    SOURCES DE DONNÉES                       │
│           🌪️ T101    🌪️ T102    🌪️ T103                   |
│  (Python Generators - MQTT Publishers)                      │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   MQTT BROKER (Mosquitto)                   │
│  Topics: wind/turbine/data/T101, T102, T103                 │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  NŒUD 1: DATA COLLECTOR & CLEANER                           │
│  - MQTT Subscriber (écoute les 3 topics)                    │
│  - Data Cleaner (remplace NaN/null)                         │
│  - Validation des données                                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  NŒUD 2: REDIS PUB/SUB STREAMING                            │
│  - 3 Channels Redis (turbine:stream:T101, T102, T103)       │
│  - Distribution en temps réel                               │
│  - Transfert vers MongoDB                                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  NŒUD 3: MONGODB STORAGE                                    │
│  - Collection: turbine_data                                 │
│  - Index: (turbine_id, timestamp)                           │ 
│  - Stockage long terme distribué par turbine_id             │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  QUERY ENGINE - KPIs                                        │
│  1. Vitesse moyenne du vent                                 │
│  2. Efficacité de production                                │
│  3. Production d'énergie quotidienne                        │
│  4. Total d'énergie exportée                                │
└─────────────────────────────────────────────────────────────┘

- Collecte et Nettoyage des Données (Nœud 1)
Le premier nœud agit comme point d'entrée du système. Il s'abonne aux trois topics MQTT (wind/turbine/data/T101, T102, T103) et reçoit les messages JSON générés par les éoliennes. Chaque message contient la vitesse du vent, la puissance produite et l'énergie exportée. Le nœud effectue un nettoyage essentiel des données en détectant et remplaçant les valeurs NaN ou invalides par null, conformément aux exigences du projet. Cette étape garantit l'intégrité des données avant leur transmission. Une fois nettoyées, les données sont enrichies avec un timestamp de traitement et publiées vers le système de streaming Redis.

- Distribution via Redis Pub/Sub (Nœud 2)
Le deuxième nœud implémente un système de streaming basé sur Redis Pub/Sub, une technologie NoSQL conforme aux contraintes du projet. Trois canaux Redis sont créés, un par éolienne (turbine:stream:T101, T102, T103), permettant une distribution logique des données par source. Ce nœud s'abonne à ces canaux et agit comme passerelle entre le flux temps réel et le stockage persistant. Cette architecture permet de séparer les responsabilités : le traitement en streaming reste léger et réactif, tandis que la persistance est déléguée à MongoDB. La distribution des données par canal Redis démontre clairement le principe de répartition demandé dans le projet, chaque turbine ayant son propre flux indépendant.

- Stockage et Requêtes (Nœud 3)
Le troisième nœud gère le stockage long terme dans MongoDB avec une collection turbine_data indexée sur (turbine_id, timestamp) pour optimiser les requêtes temporelles. Le principe de distribution est implémenté via une stratégie de sharding conceptuelle par turbine_id, où chaque éolienne peut être considérée comme une partition logique des données. Le moteur de requêtes exploite les capacités d'agrégation de MongoDB pour calculer les quatre KPIs demandés : vitesse moyenne du vent par éolienne (via $avg), efficacité de production calculée comme ratio puissance/vitesse (via $divide et $avg), production d'énergie quotidienne par groupement de dates (via $group et $sum), et total d'énergie exportée cumulée pour l'ensemble du parc. Les index permettent des requêtes rapides même sur de grands volumes de données historiques.
