from apps.dto.user_dto import UserDto
from apps.controllers._base_controller import BaseController
from apps.models.brand_app_model import BrandApp
from apps.models.user_model import UserModel
from flask import request

@UserDto.api.route('')
class Users(BaseController):
    @UserDto.api.param('page', '', _in='query', required=False, default=1)
    @UserDto.api.param('limit', '', _in='query', required=False, default=15)
    def get(self):
        query = UserModel.query
        return self.json_response(self.paginate(request, query))
    


@UserDto.api.route('/<id>')
class User(BaseController):
    @UserDto.api.param('id', '', _in='path', required=True)
    def get(self,id):
        user = UserModel.query.filter_by(id=id).first()
        if not user:
            return self.json_response(None, 404)
        return self.json_response(user.to_dict())