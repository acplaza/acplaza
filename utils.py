import base64
import flask.json

class CustomJSONEncoder(flask.json.JSONEncoder):
	def __init__(self, **kwargs):
		kwargs['ensure_ascii'] = False
		super().__init__(**kwargs)

	def default(self, x):
		if isinstance(x, bytes):
			return base64.b64encode(x).decode()
		return super().default(x)
