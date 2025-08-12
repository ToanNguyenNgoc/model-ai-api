from flask import Request
from flask import request as route_request
from flask_restx import Resource
import math
from flask_jwt_extended import (get_jwt_identity)
from apps.models.user_model import UserModel

class BaseController(Resource):
    @staticmethod
    def paginate(request:Request, query):
        page = request.args.get('page', default=1, type=int)
        limit = request.args.get('limit', default=15, type=int)
        offset = (page - 1) * limit
        total = query.count()
        data = query.offset(offset).limit(limit).all()
        total_page = math.ceil(total / limit)
        paginate = {
            'current_page': page,
            'data': [item.to_dict() for item in data],
            'total_page': total_page,
            'next_page': total_page if page + 1 >= total_page else page + 1
        }
        return paginate

    @staticmethod
    def json_response(data=None, status_code=200, message=None):
        response = {
            'status':status_code,
            'message':message,
            'context': data
        }
        return response, status_code

    @staticmethod
    def handle_error(error_msg='Server error', status_code=500):
        return {"message": error_msg}, status_code

    @staticmethod
    def get_request():
        return route_request.json

    @staticmethod
    def on_user():
        try:
            user_id = get_jwt_identity()
            user_response = UserModel.query.filter_by(id=int(user_id)).first()
            return user_response
        except:
            BaseController.json_response(None,401,'Unauthorized')
