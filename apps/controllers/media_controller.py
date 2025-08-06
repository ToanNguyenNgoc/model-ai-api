import os
from flask import request, send_from_directory
from apps.controllers._base_controller import BaseController
from apps.dto.media_dto import MediaDto
from werkzeug.utils import secure_filename
from datetime import datetime


@MediaDto.api.route('/upload')
class UploadMediaDto(BaseController):
    @MediaDto.api.expect(MediaDto.upload_parser)
    def post(self):
        upload_dir = 'media/uploads'
        os.makedirs(upload_dir, exist_ok=True)
        ars = MediaDto.upload_parser.parse_args()
        file = ars['file']
        filename = f"{int((datetime.now()).timestamp())}_{secure_filename(file.filename)}"
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)
        file_url = request.host_url.rstrip('/') + f"/api/media/upload/{filename}"
        file_response = {
            'filename': filename,
            'file_path': f'{upload_dir}/{filename}',
            'original_url': file_url,
            'mimetype': file.mimetype,
            'size': os.path.getsize(file_path),
        }
        return self.json_response(file_response)

@MediaDto.api.route('/upload/<filename>')
class GetMediaDto(BaseController):
    def get(self, filename):
        upload_dir = 'media/uploads'
        file_path = os.path.join(upload_dir, filename)

        if not os.path.isfile(file_path):
            return self.json_response(None, 404, 'File not found')
        return send_from_directory(upload_dir, filename)

