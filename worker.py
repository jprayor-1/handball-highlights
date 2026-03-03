import os
import logging
from redis import Redis
from rq import Worker, Queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

redis_url = os.environ.get("REDIS_URL")
if not redis_url:
    raise RuntimeError("REDIS_URL environment variable is not set")

redis_conn = Redis.from_url(redis_url)
queues = [Queue("video", connection=redis_conn)]

if __name__ == "__main__":
    worker = Worker(queues, connection=redis_conn)
    worker.work(with_scheduler=False)
