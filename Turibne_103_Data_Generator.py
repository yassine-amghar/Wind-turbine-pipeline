import json
import time
import random
import numpy as np
from datetime import datetime
import paho.mqtt.client as mqtt

# ======================
# MQTT CONFIGURATION
# ======================
BROKER = "localhost"
PORT = 1883
TOPIC = "wind/turbine/data/T103"

client = mqtt.Client()
client.connect(BROKER, PORT, 60)

# ======================
# STATISTIQUES
# ======================
WIND_MEAN = 6.168942
WIND_STD = 2.729510
WIND_MIN = 0.114947
WIND_MAX = 22.910000

POWER_MEAN = 520.897390
POWER_STD = 544.783016
POWER_MIN = -16.652830
POWER_MAX = 2072.454590

ENERGY_MAX = 438.000000

NULL_PROBABILITY = 0.02   # 5% de valeurs nulles

np.random.seed(42)

# ======================
# GENERATION D'UN MESSAGE
# ======================
def maybe_null(value):
    return None if random.random() < NULL_PROBABILITY else value

def generate_message(row_id):
    # Wind speed
    wind_speed = np.random.normal(WIND_MEAN, WIND_STD)
    wind_speed = float(np.clip(wind_speed, WIND_MIN, WIND_MAX))
    wind_speed = maybe_null(round(wind_speed, 3))

    # Power
    if wind_speed is None:
        power = None
    else:
        power = wind_speed * np.random.normal(90, 25)

        if random.random() < 0.1:
            power = -abs(power)

        power = float(np.clip(power, POWER_MIN, POWER_MAX))
        power = maybe_null(round(power, 2))

    # Energy export
    if power is None or power <= 0:
        energy = 0.0
    else:
        energy = power * 0.25
        energy = float(np.clip(energy, 0, ENERGY_MAX))

    payload = {
        "turbine_id": "T103",
        "# row": row_id,
        "data": {
            "# Date and time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "Wind speed (m/s)": wind_speed,
            "Energy Export (kWh)": round(energy, 2),
            "Power (kW)": power
        }
    }

    return payload

# ======================
# PUBLISH LOOP
# ======================
row = 0
while True:
    message = generate_message(row)
    pretty_json = json.dumps(message,indent=4)
    client.publish(TOPIC, pretty_json)
    
    print(pretty_json)

    row += 1
    # Augmenter ou diminuer la vitesse de production des données
    time.sleep(1)
