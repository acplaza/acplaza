import base64
import flask.json
import json
from werkzeug.routing import BaseConverter, ValidationError
from werkzeug.exceptions import HTTPException
from acnh.designs import DESIGN_CODE_RE

def init_app(app):
	app.json_encoder = CustomJSONEncoder
	app.url_map.converters['design_code'] = DesignCodeConverter
	app.errorhandler(HTTPException)(handle_exception)

class CustomJSONEncoder(flask.json.JSONEncoder):
	def __init__(self, **kwargs):
		kwargs['ensure_ascii'] = False
		super().__init__(**kwargs)

	def default(self, x):
		if isinstance(x, bytes):
			return base64.b64encode(x).decode()
		return super().default(x)

class DesignCodeConverter(BaseConverter):
	def to_python(self, value):
		if not DESIGN_CODE_RE.fullmatch(value):
			raise ValidationError
		return value

	def to_url(self, value):
		return value

def handle_exception(ex):
	"""Return JSON instead of HTML for HTTP errors."""
	# start with the correct headers and status code from the error
	response = ex.get_response()
	# replace the body with JSON
	response.data = json.dumps({
		'http_status': ex.code,
		'http_status_name': ex.name,
		'http_status_description': ex.description,
	})
	response.content_type = 'application/json'
	return response
