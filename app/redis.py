import redis
import app.core

def add_farm_to_redis(farm_id, timezone):
    try:
        if not app.core.REDIS_HOST or not app.core.REDIS_PORT:
            raise ValueError("Redis host or port is missing")

        with redis.Redis(
            host=app.core.REDIS_HOST,
            port=int(app.core.REDIS_PORT),
            username=getattr(app.core, "REDIS_USERNAME", "default"),
            password=app.core.REDIS_PASSWORD,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            health_check_interval=30,
        ) as client:
            with client.pipeline(transaction=True) as pipe:
                pipe.hset(app.core.REDIS_TIME_KEY, str(farm_id), timezone)
                pipe.persist(app.core.REDIS_TIME_KEY)
                results = pipe.execute()

        action = "added" if results[0] == 1 else "updated"
        return {
            "success": True,
            "action": action,
            "message": f"Farm {farm_id} {action} with timezone {timezone}"
        }

    except (redis.RedisError, TypeError, ValueError):
        return {
            "success": False,
            "message": "Failed to save farm timezone to Redis"
        }
