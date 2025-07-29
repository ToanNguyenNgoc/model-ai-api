from flask import Flask, request, jsonify
from dotenv import load_dotenv
import os
from flask_restx import Api
from apps.configs.mysql_config import MysqlConfig
from apps.route.route import Route
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

api = Api(
    app,
    version='1.0',
    title='Myspa Model AI API',
    description='A simple API',
    url_prefix='/api/docs'
)
MysqlConfig(app).connection()
Route(api).instance()
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
