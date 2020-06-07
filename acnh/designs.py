# © 2020 io mintz <io@mintz.cc>

import io
import re
import urllib.parse
from http import HTTPStatus
from functools import wraps

import msgpack

from .common import config, authenticate_aauth, authenticate_acnh, ACNHError, InvalidFormatError, ACNHClient
from . import utils

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

# not an invalid format error because it's not constrainable to a regex
class InvalidDesignError(DesignError):
	code = 26
	message = 'invalid design'

class InvalidPaletteError(DesignError):
	code = 27
	message = 'limit 15 colors'

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
def delete_design(acnh, design_id) -> None:
	resp = acnh.request('DELETE', '/api/v1/designs/' + str(design_id))
	if resp.status_code == HTTPStatus.NOT_FOUND:
		raise UnknownDesignCodeError

@authenticated
def create_design(acnh, design_data) -> int:
	"""create a design. returns the created design ID."""
	resp = acnh.request('POST', '/api/v1/designs', data=msgpack.dumps(design_data))
	if resp.status_code == HTTPStatus.BAD_REQUEST:
		raise InvalidDesignError
	data = msgpack.loads(resp.content)
	return data['id']
