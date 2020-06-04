# © 2020 io mintz <io@mintz.cc>

# ACNH API is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# ACNH API is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with ACNH API. If not, see <https://www.gnu.org/licenses/>.

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
