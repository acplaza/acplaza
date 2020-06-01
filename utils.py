import os.path
import time

def load_cached(path, callback, *, duration=24 * 60 * 60):
	def refresh_cache():
		rv = callback()
		with open(path, 'w') as f:
			f.write(rv)
		return rv

	now = time.time()
	try:
		last_modified = os.stat(path).st_mtime
	except FileNotFoundError:
		return refresh_cache()

	if now - last_modified > duration:
		return refresh_cache()
	else:
		with open(path) as f:
			return f.read()
