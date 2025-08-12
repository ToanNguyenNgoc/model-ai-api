from flask_restx import Namespace, fields

class OrganizationDto:
  api = Namespace('Organization')
  organizations = api.model('organizations',{
        'page': fields.Integer(),
        'limit': fields.Integer(),
    })