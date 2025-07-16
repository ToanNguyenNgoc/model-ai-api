from apps.controllers._base_controller import BaseController
from apps.dto.auth_dto import AuthDto
from flask import request
from apps.models.user_model import UserModel

@AuthDto.api.route('/login')
class Login(BaseController):
  @AuthDto.api.expect(AuthDto.login_model)
  def post(self):
    email = request.json['email']
    password = request.json['password']
    user = UserModel.query.filter(UserModel.email.collate('utf8mb4_bin') == email).first()
    if not user:
      return self.json_response(None, 404,'User not found')
    if not user.is_active:
      return self.json_response(None, 403, 'This account is deactivate!')
    return self.json_response(user.to_dict())