from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()

class MysqlConfig:
    def __init__(self, app):
        self.app = app

    def connection(self):
        user = os.getenv("DB_USERNAME", "root")
        password = os.getenv("DB_PASSWORD", "")
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "3306")
        database = os.getenv("DB_DATABASE", "flask_api")

        db_url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"

        self.app.config['SQLALCHEMY_DATABASE_URI'] = db_url
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

        db.init_app(self.app)

        try:
            with self.app.app_context():
                conn = db.engine.connect()
                conn.close()
                print("Connected to MySQL DB")
        except Exception as e:
            print(f'Failed to connect to MySQL DB',e)
        return db