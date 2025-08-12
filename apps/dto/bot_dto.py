from flask_restx import Namespace, fields

class BotDto:
  api = Namespace('Bot')
  post_message = api.model('post_message',{
    'user_id': fields.String(required=False),
    'message': fields.String(required=True)
  })