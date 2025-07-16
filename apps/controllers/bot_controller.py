from apps.dto.bot_dto import BotDto
from apps.controllers._base_controller import BaseController

@BotDto.api.route('/messages')
class Message(BaseController):
  def get(self):
    return self.json_response([])
  
  @BotDto.api.expect(BotDto.post_message, validate=True)
  def post(self):
    return self.json_response([])
  