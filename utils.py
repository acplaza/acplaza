import os.path
import time

import flask.json

def load_cached(path, callback, *, duration=24 * 60 * 60, _cache={}):
	now = time.time()

	def refresh_cache():
		rv = callback()
		with open(path, 'w') as f:
			f.write(rv)
		_cache[path] = rv, now
		return rv

	try:
		rv, last_modified = _cache[path]
	except KeyError:
		pass
	else:
		if now - last_modified > duration:
			return refresh_cache()
		return rv

	# not in cache

	try:
		last_modified = os.stat(path).st_mtime
	except FileNotFoundError:
		return refresh_cache()

	# not in cache but file exists

	if now - last_modified > duration:
		return refresh_cache()

	# not in cache, file exists, and the file is young enough

	with open(path) as f:
		rv = f.read()
	_cache[path] = rv, now
	return rv

class UnicodeJSONEncoder(flask.json.JSONEncoder):
	def __init__(self, **kwargs):
		kwargs['ensure_ascii'] = False
		super().__init__(**kwargs)
