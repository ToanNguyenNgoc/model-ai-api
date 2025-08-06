from apps.dto.bot_dto import BotDto
from apps.controllers._base_controller import BaseController
import os
from openai import OpenAI
from difflib import get_close_matches
import re
from apps.utils.spa_locations import spa_locations
from apps.utils.spa_services import spa_services



# load_dotenv()
# openai.api_key = os.getenv("OPENAI_API_KEY", "")

def is_request_for_spa_intro(message, spa_name):
    message_lower = message.lower()
    name_lower = spa_name.lower()

    # Nếu chỉ đơn giản là tên spa → yêu cầu giới thiệu
    if message_lower.strip() == name_lower:
        return True

    # Một số cách hỏi phổ biến để giới thiệu spa
    patterns = [
        fr"giới thiệu.*{re.escape(name_lower)}",
        fr"{re.escape(name_lower)}.*là gì",
        fr"thông tin.*{re.escape(name_lower)}",
        fr"{re.escape(name_lower)}.*ở đâu",
        fr"{re.escape(name_lower)}.*có.*tốt.*không",
    ]

    return any(re.search(p, message_lower) for p in patterns)


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
        import re
        from difflib import get_close_matches
        from openai import OpenAI
        import os

        message = self.get_request()['message']
        client = OpenAI(api_key=os.getenv('A_SECRET_KEY'))

        # 🔹 Danh sách spa và dịch vụ
        spa_names = list(spa_services.keys())
        city_keywords = self.extract_city_keywords(spa_locations)
        keywords = self.extract_keywords(message)

        # 🔹 Nếu là câu hỏi tổng quát về chăm sóc da → dùng GPT trả lời
        if self.is_general_skin_question_gpt(message, client):
            return self.reply_with_gpt(message, client)

        # 🔹 Nếu có địa điểm và từ khóa (spa trị mụn ở HCM, Đà Nẵng,...)
        city = self.extract_city_from_message(message, city_keywords)
        if city:
            matched_spas = self.find_spas_by_city_and_keywords(spa_locations, city, keywords)
            if matched_spas:
                reply = [f"📍 Các spa tại **{city.title()}** phù hợp với yêu cầu của bạn:"]
                for spa in matched_spas:
                    reply.append(f"- **{spa['name']}** — {spa['address']}")
                    if spa.get("description"):
                        reply.append(f"  {spa['description']}")
                return self.json_response("\n".join(reply))

        # 🔹 Nếu có match tên dịch vụ chính xác → trả thông tin dịch vụ
        exact_service = self.find_exact_service_by_name(message, spa_services)
        if exact_service:
            s = exact_service["service"]
            spa_name = exact_service["spa_name"]
            return self.json_response(f"💆 **{s['name']}** tại **{spa_name}**:\n{s['description']}")

        # 🔹 Nếu có match tên spa
        matched_spa = self.detect_spa_in_message(message, spa_names)
        if matched_spa:
            services = spa_services.get(matched_spa, [])

            if self.is_request_for_spa_intro(message, matched_spa):
                info = next((s for s in spa_locations if s["name"] == matched_spa), None)
                if info and info.get("description"):
                    return self.json_response(f"📍 **{matched_spa}** — {info['address']}\n\n{info['description']}")

            matched_services = self.filter_services_by_keywords(services, keywords)
            if matched_services:
                reply = [f"💆 Dịch vụ tại **{matched_spa}** phù hợp với yêu cầu của bạn:"]
                for s in matched_services:
                    reply.append(f"- {s['name']}: {s['description']}")
                return self.json_response("\n".join(reply))

            # Nếu không có từ khóa dịch vụ cụ thể → mô tả spa
            info = next((s for s in spa_locations if s["name"] == matched_spa), None)
            if info and info.get("description"):
                return self.json_response(f"📍 **{matched_spa}** — {info['address']}\n\n{info['description']}")

            # Nếu có dịch vụ nhưng không match keyword → liệt kê hết
            if services:
                reply = [f"🤔 Đây là các dịch vụ tại **{matched_spa}**:"]
                for s in services:
                    reply.append(f"- {s['name']}: {s['description']}")
                return self.json_response("\n".join(reply))

            return self.json_response(f"Hiện tại **{matched_spa}** chưa có dịch vụ nào được cập nhật.")

        # 🔹 Nếu không có tên spa → tìm từ khóa trong dịch vụ tất cả spa
        matched_spa_services = []
        for spa_name, services in spa_services.items():
            matched_services = self.filter_services_by_keywords(services, keywords)
            if matched_services:
                matched_spa_services.append((spa_name, matched_services))

        if matched_spa_services:
            reply = ["💡 Các spa có dịch vụ phù hợp với yêu cầu của bạn:"]
            for spa_name, services in matched_spa_services:
                reply.append(f"\n- **{spa_name}**")
                for s in services:
                    reply.append(f"  - {s['name']}: {s['description']}")
            return self.json_response("\n".join(reply))

        # 🔹 Cuối cùng fallback dùng GPT
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

    # -------------------------------
    # 🔸 Utility methods bên dưới:
    # -------------------------------
    def extract_keywords(self, text):
        words = re.findall(r'\b[\wÀ-Ỵà-ỵ]{3,}\b', text.lower())
        return list(set(words))

    def detect_spa_in_message(self, message, spa_names):
        message_lower = message.lower()
        for name in spa_names:
            if name.lower() in message_lower:
                return name
        matches = get_close_matches(message_lower, [s.lower() for s in spa_names], n=1, cutoff=0.5)
        if matches:
            return next((s for s in spa_names if s.lower() == matches[0]), None)
        return None

    def filter_services_by_keywords(self, services, keywords):
        return [s for s in services if any(k in (s["name"] + " " + s["description"]).lower() for k in keywords)]

    def find_exact_service_by_name(self, message, spa_services):
        message_lower = message.lower()
        for spa_name, services in spa_services.items():
            for s in services:
                if s["name"].lower() in message_lower:
                    return {"spa_name": spa_name, "service": s}
        return None

    def is_request_for_spa_intro(self, message, spa_name):
        message_lower = message.lower()
        name_lower = spa_name.lower()
        if message_lower.strip() == name_lower:
            return True
        patterns = [
            fr"giới thiệu.*{re.escape(name_lower)}",
            fr"{re.escape(name_lower)}.*là gì",
            fr"thông tin.*{re.escape(name_lower)}",
            fr"{re.escape(name_lower)}.*ở đâu",
            fr"{re.escape(name_lower)}.*tốt.*không",
        ]
        return any(re.search(p, message_lower) for p in patterns)

    def extract_city_keywords(self, spa_locations):
        city_map = {}
        for spa in spa_locations:
            parts = [p.strip().lower() for p in spa["address"].split(",")]
            if len(parts) >= 2:
                city = parts[-1]
                if city not in city_map:
                    city_map[city] = set()
                city_map[city].add(city)
                if city == "hồ chí minh":
                    city_map[city].update(["tp hcm", "tp. hcm", "sài gòn", "hcm"])
                elif city == "hà nội":
                    city_map[city].update(["hn"])
        return {k: list(v) for k, v in city_map.items()}

    def extract_city_from_message(self, message, city_keywords):
        message_lower = message.lower()
        for city, keywords in city_keywords.items():
            if any(k in message_lower for k in keywords):
                return city
        return None

    def find_spas_by_city_and_keywords(self, spa_locations, city, keywords):
        results = []
        for spa in spa_locations:
            text = (spa["name"] + " " + spa["address"] + " " + spa.get("description", "")).lower()
            if city in spa["address"].lower() or city in text:
                if any(k in text for k in keywords):
                    results.append(spa)
        return results

    def is_general_skin_question_gpt(self, message, client):
        system_msg = (
            "Bạn là một bộ lọc phân loại câu hỏi.\n"
            "Nếu người dùng hỏi về các vấn đề liên quan đến chăm sóc da, làm đẹp, mụn, thâm, nám, lão hóa, dưỡng da, spa nói chung (nhưng không hỏi tên dịch vụ cụ thể), trả lời: YES.\n"
            "Nếu không phải, trả lời: NO.\n"
            "Chỉ trả về một từ duy nhất: YES hoặc NO."
        )
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": message},
            ],
        )
        return completion.choices[0].message.content.strip().upper() == "YES"

    def reply_with_gpt(self, message, client):
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Bạn là chuyên gia da liễu. Trả lời ngắn gọn, rõ ràng, dễ hiểu cho người dùng đang hỏi về các vấn đề về da hoặc làm đẹp."},
                {"role": "user", "content": message},
            ],
        )
        return self.json_response(completion.choices[0].message.content.strip())

