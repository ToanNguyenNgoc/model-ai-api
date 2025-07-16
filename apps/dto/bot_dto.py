from flask_restx import Namespace, fields

class BotDto:
  api = Namespace('Bot')
  post_message = api.model('post_message',{
    'message': fields.String(required=True)
  })