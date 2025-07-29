from apps.dto.bot_dto import BotDto
from apps.controllers._base_controller import BaseController
import os
from openai import OpenAI
from difflib import get_close_matches
import re



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
    # system_prompt = """
    # Bạn là một chuyên gia tư vấn spa và thẩm mỹ viện.
    # Bạn **chỉ được trả lời** các câu hỏi liên quan đến:
    # - chăm sóc da, tóc, cơ thể
    # - các liệu trình spa, thẩm mỹ
    # - tư vấn làm đẹp, sản phẩm dưỡng da, chăm sóc sau dịch vụ
    #
    # Nếu người dùng hỏi về chủ đề ngoài lĩnh vực đó (như chính trị, thể thao, IT,...), bạn phải trả lời:
    # "Xin lỗi, tôi chỉ hỗ trợ các câu hỏi về làm đẹp, chăm sóc da và spa."
    #
    # Trả lời thân thiện, rõ ràng và ngắn gọn.
    # """

    spa_locations = [
      {"name": "Spa Lily", "address": "123 Lê Lợi, Quận 1, TP. Hồ Chí Minh"},
      {"name": "Thẩm mỹ viện Hoa Mai", "address": "456 Hai Bà Trưng, Quận 3, TP. Hồ Chí Minh"},
      {"name": "PMT", "address": "456 Hai Bà Trưng, Quận 3, TP. Hồ Chí Minh"},
      {"name": "Bella Spa", "address": "789 Nguyễn Văn Cừ, Quận 5, TP. Hồ Chí Minh"},
      {"name": "Serenity Spa", "address": "88 Phan Đình Phùng, TP. Đà Nẵng"},
    ]
    spa_info = "\n".join([f"- {spa['name']} — {spa['address']}" for spa in spa_locations])

    system_prompt = f"""
        Bạn là một chuyên gia tư vấn spa và thẩm mỹ viện. Bạn có danh sách các spa sau:

        {spa_info}

        Nếu người dùng hỏi tìm spa ở tỉnh/thành nào, bạn chỉ được gợi ý từ danh sách trên.

        Nếu câu hỏi không liên quan đến làm đẹp hoặc spa, hãy trả lời: "Xin lỗi, tôi chỉ hỗ trợ các câu hỏi về làm đẹp, chăm sóc da và spa."

        Trả lời thân thiện, đúng thông tin.
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


# v2
@BotDto.api.route('/messages/v2')
class MessageV2(BaseController):
    @BotDto.api.expect(BotDto.post_message, validate=True)
    def post(self):
        message = self.get_request()['message']
        client = OpenAI(api_key=os.getenv('A_SECRET_KEY'))

        # Danh sách spa
        spa_locations = [
            {"name": "Spa Lily", "address": "123 Lê Lợi, Quận 1, TP. Hồ Chí Minh"},
            {"name": "Thẩm mỹ viện Hoa Mai", "address": "456 Hai Bà Trưng, Quận 3, TP. Hồ Chí Minh"},
            {"name": "PMT", "address": "456 Hai Bà Trưng, Quận 3, TP. Hồ Chí Minh"},
            {"name": "Bella Spa", "address": "789 Nguyễn Văn Cừ, Quận 5, TP. Hồ Chí Minh"},
            {"name": "Serenity Spa", "address": "88 Phan Đình Phùng, TP. Đà Nẵng"},
        ]

        # Dịch vụ từng spa
        spa_services = {
            "Spa Lily": [
                {"name": "Massage toàn thân", "description": "Thư giãn với tinh dầu thiên nhiên trong 60 phút"},
                {"name": "Chăm sóc da mặt", "description": "Làm sạch sâu, cấp ẩm, chống lão hóa"}
            ],
            "Thẩm mỹ viện Hoa Mai": [
                {"name": "Tắm trắng phi thuyền", "description": "Làm sáng da bằng công nghệ ánh sáng"},
                {"name": "Trị mụn chuyên sâu", "description": "Chiết mụn, xông hơi, kháng viêm"}
            ],
            "Bella Spa": [
                {"name": "Gội đầu dưỡng sinh", "description": "Thư giãn da đầu, vai gáy bằng thảo dược"},
                {"name": "Ủ trắng collagen", "description": "Tái tạo da sáng mịn bằng collagen tự nhiên"}
            ]
        }

        spa_names = list(spa_services.keys())

        # 🔍 Tách từ khóa bằng regex (có thể mở rộng)
        def extract_keywords(text):
            words = re.findall(r'\b[\wÀ-Ỵà-ỵ]{3,}\b', text.lower())
            return list(set(words))

        # 🔍 Phát hiện tên spa trong câu hỏi
        def detect_spa_in_message(message, spa_names):
            message_lower = message.lower()
            for name in spa_names:
                if name.lower() in message_lower:
                    return name
            matches = get_close_matches(message_lower, [s.lower() for s in spa_names], n=1, cutoff=0.5)
            if matches:
                return next((s for s in spa_names if s.lower() == matches[0]), None)
            return None

        # 🔍 Lọc dịch vụ có chứa từ khóa
        def filter_services_by_keywords(services, keywords):
            results = []
            for s in services:
                combined_text = (s["name"] + " " + s["description"]).lower()
                if any(k in combined_text for k in keywords):
                    results.append(s)
            return results

        # 🧠 Xử lý theo logic nội bộ
        matched_spa = detect_spa_in_message(message, spa_names)
        if matched_spa:
            keywords = extract_keywords(message)
            services = spa_services.get(matched_spa, [])
            matched_services = filter_services_by_keywords(services, keywords)

            if matched_services:
                reply_lines = [f"💆 Dịch vụ tại **{matched_spa}** phù hợp với yêu cầu của bạn:"]
                for s in matched_services:
                    reply_lines.append(f"- {s['name']}: {s['description']}")
                return self.json_response("\n".join(reply_lines))
            elif services:
                reply_lines = [f"🤔 Hiện chưa thấy dịch vụ cụ thể, nhưng đây là danh sách tại **{matched_spa}**:"]
                for s in services:
                    reply_lines.append(f"- {s['name']}: {s['description']}")
                return self.json_response("\n".join(reply_lines))
            else:
                return self.json_response(f"Hiện tại {matched_spa} chưa có dịch vụ nào được cập nhật.")

        # 🤖 Nếu không nhận diện được spa → fallback GPT
        spa_info = "\n".join([f"- {spa['name']} — {spa['address']}" for spa in spa_locations])
        system_prompt = f"""
        Bạn là một chuyên gia tư vấn spa và thẩm mỹ viện. Bạn có danh sách các spa sau:

        {spa_info}

        Nếu người dùng hỏi tìm spa ở tỉnh/thành nào, bạn chỉ được gợi ý từ danh sách trên.

        Nếu người dùng hỏi về dịch vụ của một spa cụ thể, hãy trả lời đúng tên dịch vụ và mô tả (nếu bạn biết).

        Nếu câu hỏi không liên quan đến làm đẹp hoặc spa, hãy trả lời:
        "Xin lỗi, tôi chỉ hỗ trợ các câu hỏi về làm đẹp, chăm sóc da và spa."

        Trả lời thân thiện, rõ ràng và ngắn gọn.
        """

        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
        )
        return self.json_response(completion.choices[0].message.content.strip())