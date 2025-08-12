from functools import wraps
from flask_jwt_extended import verify_jwt_in_request
from apps.controllers._base_controller import BaseController

def auth_required():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            try:
                verify_jwt_in_request()
            except Exception as e:
                return BaseController.json_response(None,401,'Unauthorized')
            return fn(*args, **kwargs)
        return decorator
    return wrapper