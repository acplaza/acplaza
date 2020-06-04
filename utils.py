import flask.json

class UnicodeJSONEncoder(flask.json.JSONEncoder):
	def __init__(self, **kwargs):
		kwargs['ensure_ascii'] = False
		super().__init__(**kwargs)
