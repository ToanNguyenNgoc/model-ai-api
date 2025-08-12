from apps.dto.organization_dto import OrganizationDto
from apps.controllers._base_controller import BaseController

@OrganizationDto.api.route('')
class Organizations(BaseController):
  def get(self):
    return self.json_response({})