from flask_restx import Namespace, fields

class AIDto:
  api = Namespace('AI')
  post_message = api.model('post_message',{
    'user_id': fields.String(required=False),
    'message': fields.String(required=True)
  })