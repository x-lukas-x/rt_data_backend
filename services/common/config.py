import os


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://rtdata:rtdata@postgres:5432/rtdata"
)
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
SHOP_EVENTS_TOPIC = "shop-events"
SHOP_NOTIFICATIONS_TOPIC = "shop-notifications"
DEAD_LETTER_TOPIC = "dead-letter"
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://inventory-service:8080")
READ_API_URL = os.getenv("READ_API_URL", "http://read-service:8080")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8080")
SHOP_ID = os.getenv("SHOP_ID", "shop-a")
