from flask_restx import Namespace, fields

class AuthDto:
  api = Namespace('Auth')
  login_model = api.model('login_model',{
    'email': fields.String(required=True),
    'password': fields.String(required=True)
  })