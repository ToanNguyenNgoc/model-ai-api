from flask_restx import Namespace, fields

class UserDto:
    api = Namespace('User')
    users = api.model('users',{
        'page': fields.Integer(),
        'limit': fields.Integer(),
    })