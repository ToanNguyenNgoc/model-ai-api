from apps.dto.auth_dto import AuthDto
from apps.controllers import auth_controller
from apps.dto.user_dto import UserDto
from apps.controllers import user_controller
from apps.dto.bot_dto import BotDto
from apps.controllers import bot_controller
from apps.dto.media_dto import MediaDto
from apps.controllers import media_controller
from apps.dto.organization_dto import OrganizationDto
from apps.controllers import org_controller
from apps.dto.ai_dto import AIDto
from apps.controllers import ai_controller

class Route:
    def __init__(self, api):
        self.api = api

    def instance(self):
        self.api.add_namespace(AuthDto.api, path='/api/auth')
        self.api.add_namespace(UserDto.api, path='/api/users')
        self.api.add_namespace(OrganizationDto.api, path='/api/organizations')
        self.api.add_namespace(BotDto.api, path='/api/bots')
        self.api.add_namespace(AIDto.api, path='/api/ai')
        self.api.add_namespace(MediaDto.api, path='/api/media')
        
        return

