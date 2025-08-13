from apps.dto.ai_dto import AIDto
from apps.controllers._base_controller import BaseController
import os
from openai import OpenAI
from apps.extensions import cache
from apps.vector.training_vector import TrainingVector
from flask_restx import Resource
from apps.ai.intents import parse_message_with_llm, enrich_slots
from apps.ai.policy import route


@AIDto.api.route('/messages')
class PostAI(BaseController, Resource):
    @AIDto.api.expect(AIDto.post_message, validate=True)
    def post(self):
        req = self.get_request() or {}
        message = req.get('message', '')
        user_id = req.get('user_id') or 123
        conversation_key = f"chat:{user_id}"
        history = cache.get(conversation_key) or []
        history.append({"role": "user", "content": message})

        helper = TrainingVector()
        client = OpenAI(api_key=os.getenv("A_SECRET_KEY"))

        # --- NLU 1 lần ---
        nlu = parse_message_with_llm(client, message, history)
        slots = enrich_slots(nlu)

        # --- Env cho policy ---
        env = {
            "helper": helper,
            "conversation_key": conversation_key,
            "history": history,
            "user_id": user_id,
            "client": client,
            "message": message,
            "slots": slots,
        }

        # --- Route theo priority ---
        return route(nlu, env)