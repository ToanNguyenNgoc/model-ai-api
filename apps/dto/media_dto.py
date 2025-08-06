from flask_restx import Namespace, reqparse
from werkzeug.datastructures import FileStorage

class MediaDto:
    api = Namespace('Media')
    upload_parser = reqparse.RequestParser()
    upload_parser.add_argument(
        'file',
        location='files',
        type=FileStorage,
        required=True,
        help='The file to upload'
    )