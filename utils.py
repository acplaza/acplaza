import base64
import json

import flask.json
from flask import current_app
from werkzeug.exceptions import HTTPException
from acnh.common import ACNHError

def init_app(app):
	app.json_encoder = CustomJSONEncoder
	app.errorhandler(ACNHError)(handle_acnh_exception)
	app.errorhandler(HTTPException)(handle_exception)

class CustomJSONEncoder(flask.json.JSONEncoder):
	def __init__(self, **kwargs):
		kwargs['ensure_ascii'] = False
		super().__init__(**kwargs)

	def default(self, x):
		if isinstance(x, bytes):
			return base64.b64encode(x).decode()
		return super().default(x)

def handle_acnh_exception(ex):
	"""Return JSON instead of HTML for ACNH errors"""
	d = ex.to_dict()
	response = current_app.response_class()
	response.status_code = d['http_status']
	response.data = json.dumps(d)
	response.content_type = 'application/json'
	return response

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
