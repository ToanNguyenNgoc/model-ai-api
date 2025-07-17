from apps.dto.bot_dto import BotDto
from apps.controllers._base_controller import BaseController
import os
from openai import OpenAI

# load_dotenv()
# openai.api_key = os.getenv("OPENAI_API_KEY", "")

@BotDto.api.route('/messages')
class Message(BaseController):
  def get(self):
    return self.json_response([])
  
  @BotDto.api.expect(BotDto.post_message, validate=True)
  def post(self):
    message = self.get_request()['message']
    client = OpenAI(api_key=os.getenv('A_SECRET_KEY'))
    system_prompt = """
    Bạn là một chuyên gia tư vấn spa và thẩm mỹ viện. 
    Bạn **chỉ được trả lời** các câu hỏi liên quan đến:
    - chăm sóc da, tóc, cơ thể
    - các liệu trình spa, thẩm mỹ
    - tư vấn làm đẹp, sản phẩm dưỡng da, chăm sóc sau dịch vụ

    Nếu người dùng hỏi về chủ đề ngoài lĩnh vực đó (như chính trị, thể thao, IT,...), bạn phải trả lời:
    "Xin lỗi, tôi chỉ hỗ trợ các câu hỏi về làm đẹp, chăm sóc da và spa."

    Trả lời thân thiện, rõ ràng và ngắn gọn.
    """
    completion = client.chat.completions.create(
      model="gpt-4o",
      messages=[
        {"role": "system", "content": system_prompt},
        {
          "role": "user",
          "content": message,
        },
      ],
    )
    return self.json_response(completion.choices[0].message.content)
