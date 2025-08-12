from flask_cors import CORS

class CORSConfig:
    def __init__(self, app):
        self.app = app

    def instance(self):
        return CORS(self.app, resources={r"/*": {"origins": "*"}})