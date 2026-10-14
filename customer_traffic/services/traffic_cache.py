
import json
import os

import redis

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "127.0.0.1"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    db=int(os.getenv("REDIS_DB", "0")),
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)

KEY_PREFIX = "client_traffic:live:"
DEFAULT_TTL = 15


def _key(pppoe_username):
    return f"{KEY_PREFIX}{pppoe_username}"


def set_live_traffic(pppoe_username, traffic, ttl=DEFAULT_TTL):
    redis_client.set(
        _key(pppoe_username),
        json.dumps(traffic),
        ex=ttl,
    )


def set_live_traffic_batch(readings, ttl=DEFAULT_TTL):
    if not readings:
        return

    with redis_client.pipeline(transaction=False) as pipe:
        for username, traffic in readings.items():
            pipe.set(
                _key(username),
                json.dumps(traffic),
                ex=ttl,
            )
        pipe.execute()


def get_live_traffic(pppoe_username):
    value = redis_client.get(_key(pppoe_username))

    if value is None:
        return None

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def set_ac_health(ac_name, health, ttl=30):
    redis_client.set(
        f"client_traffic:health:{ac_name}",
        json.dumps(health),
        ex=ttl,
    )


def get_ac_health(ac_name):
    value = redis_client.get(f"client_traffic:health:{ac_name}")

    if value is None:
        return None

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
