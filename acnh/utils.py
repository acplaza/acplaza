# © 2020 io mintz <io@mintz.cc>

import os.path
import time

def load_cached(path, callback, *, duration=24 * 60 * 60, binary=False, _cache={}):
	now = time.time()

	def refresh_cache():
		rv = callback()
		with open(path, 'wb' if binary else 'w') as f:
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

	with open(path, 'rb' if binary else 'r') as f:
		rv = f.read()
	_cache[path] = rv, now
	return rv
