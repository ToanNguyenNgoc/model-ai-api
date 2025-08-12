from flask import Flask
from dotenv import load_dotenv
import os
from apps.configs.mysql_config import MysqlConfig
from apps.configs.api_doc_config import ApiDocConfig
from apps.route.route import Route
from flask_jwt_extended import JWTManager
from apps.configs.config import Config
from apps.configs.cors_config import CORSConfig
from apps.extensions import cache

load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)

CORSConfig(app).instance()
api_doc = ApiDocConfig(app).instance()
MysqlConfig(app).connection()
Route(api_doc).instance()
JWTManager(app)
cache.init_app(app)
@app.route('/')
def index():
    return 'Home'

if __name__ == "__main__":
  port = int(os.getenv('APP_PORT', 5000))
  host = str(os.getenv('APP_HOST', 'localhost'))
  app_debug = True if os.getenv('APP_DEBUG') == 'true' else False
  print(f'Server is started: {host}:{port}')
  app.run(host=host, port=port, debug=app_debug)

# pip freeze > requirements.txt
