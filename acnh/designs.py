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

import re
import urllib.parse
from http import HTTPStatus
from functools import wraps

import msgpack
from nintendo.common.http import HTTPRequest

from .common import config, authenticate_aauth, authenticate_acnh, ACNHError, InvalidFormatError, ACNHClient

class DesignError(ACNHError):
	pass

class UnknownDesignCodeError(DesignError):
	code = 21
	message = 'unknown design code'
	http_status = HTTPStatus.NOT_FOUND

_design_code_alphabet = '0123456789BCDFGHJKLMNPQRSTVWXY'
DESIGN_CODE_ALPHABET = {c: val for val, c in enumerate(_design_code_alphabet)}

class InvalidDesignCodeError(DesignError, InvalidFormatError):
	code = 22
	message = 'invalid design code'
	_design_code_segment = f'[{_design_code_alphabet}]{{4}}'
	regex = re.compile('-'.join([_design_code_segment] * 3))
	del _design_code_segment

class UnknownCreatorIdError(DesignError):
	code = 23
	message = 'unknown creator ID'
	http_status = HTTPStatus.NOT_FOUND

class InvalidCreatorIdError(DesignError, InvalidFormatError):
	code = 24
	message = 'invalid creator ID'
	regex = re.compile('\d{4}-?\d{4}-?\d{4}', re.ASCII)

def design_id(design_code):
	code = design_code.replace('-', '')
	n = 0
	for c in code:
		n *= 30
		n += DESIGN_CODE_ALPHABET[c]
	return n

def design_code(design_id):
	digits = []
	group_count = 0
	while design_id:
		design_id, digit = divmod(design_id, 30)
		digits.append(_design_code_alphabet[digit])
		group_count += 1
		if group_count == 4:
			digits.append('-')
			group_count = 0

	if digits[-1] == '-':
		digits.pop()

	return ''.join(reversed(digits)).zfill(4 * 3 + 2)

def authenticated(func):
	@wraps(func)
	def wrapped(*args, **kwargs):
		_, id_token = authenticate_aauth()
		token = authenticate_acnh(id_token)
		acnh = ACNHClient(token)
		return func(acnh, *args, **kwargs)
	return wrapped

@authenticated
def download_design(acnh, design_id):
	resp = acnh.request('GET', '/api/v2/designs', params={
		'offset': 0,
		'limit': 1,
		'q[design_id]': design_id,
	})
	resp = msgpack.loads(resp.content)

	if not resp['total']:
		raise UnknownDesignCodeError
	if resp['total'] > 1:
		raise RuntimeError('one ID requested, but more than one returned?!')
	headers = resp['headers'][0]

	url = urllib.parse.urlparse(headers['body'])
	resp = acnh.request('GET', url.path + '?' + url.query)
	return msgpack.loads(resp.content)

@authenticated
def list_designs(acnh, creator_id: int, *, pro: bool):
	resp = acnh.request('GET', '/api/v2/designs', params={
		'offset': 0,
		'limit': 120,
		'q[player_id]': creator_id,
		'with_binaries': 'false',
	})
	resp = msgpack.loads(resp.content)
	if not resp['total']:
		raise UnknownCreatorIdError
	return resp

@authenticated
def delete_design(acnh, design_id):
	resp = acnh.request('DELETE', '/api/v1/designs/' + str(design_id))
	if resp.status_code == 404:
		raise UnknownDesignCodeError
