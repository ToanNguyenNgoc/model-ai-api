import os
from dotenv import load_dotenv

load_dotenv()
class Config:
    SECRET_KEY=os.getenv('APP_SECRET_KEY')
    JWT_SECRET_KEY=os.getenv('JWT_SECRET_KEY')

    CACHE_TYPE='RedisCache'
    CACHE_REDIS_HOST=os.getenv('REDIS_HOST')
    CACHE_REDIS_PORT=int(os.getenv('REDIS_PORT',6379))
    CACHE_REDIS_PASSWORD=os.getenv('REDIS_PASSWORD')
    CACHE_REDIS_DB=int(os.getenv('REDIS_DB',10))

    CACHE_DEFAULT_TIMEOUT = 3600  # 1 hour