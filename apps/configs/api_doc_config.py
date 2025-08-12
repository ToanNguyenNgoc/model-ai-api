from flask_restx import Api

from apps.utils.constaint import CONSTANT


class ApiDocConfig:
    def __init__(self, app):
        self.app = app
    def instance(self):
        authorizations = {
            'Bearer Auth': {
                'type': 'apiKey',
                'in': 'header',
                'name': 'Authorization',
                'description': "Enter token: **Bearer &lt;JWT&gt;**"
            }
        }
        api_doc = Api(
            app=self.app,
            version='1.0',
            title='Myspa Model AI API',
            description='A simple API',
            authorizations=authorizations,
            url_prefix='/api/docs',
            security=CONSTANT.bearer_token,
        )
        return api_doc
