# © 2020 io mintz <io@mintz.cc>

import io
import re
import urllib.parse
from http import HTTPStatus
from functools import wraps
from typing import Union

import msgpack

from ..common import acnh, ACNHError, InvalidFormatError
from .. import utils

DesignId = Union[str, int]

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

class UnknownAuthorIdError(DesignError):
	code = 23
	message = 'unknown author ID'
	http_status = HTTPStatus.NOT_FOUND

class InvalidAuthorIdError(DesignError, InvalidFormatError):
	code = 24
	message = 'invalid author ID'
	regex = re.compile('\d{4}-?\d{4}-?\d{4}', re.ASCII)

# not an invalid format error because it's not constrainable to a regex
class InvalidDesignError(DesignError):
	code = 26
	message = 'invalid design'
	http_status = HTTPStatus.BAD_REQUEST

def design_id(design_code):
	code = design_code.replace('-', '')
	n = 0
	for c in code:
		n *= 30
		n += DESIGN_CODE_ALPHABET[c]
	return n

def design_code(design_id):
	digits = []
	while design_id:
		design_id, digit = divmod(design_id, 30)
		digits.append(_design_code_alphabet[digit])

	return add_hyphens(''.join(reversed(digits)).zfill(4 * 3))

def add_hyphens(author_id: str):
	return '-'.join(utils.chunked(author_id, 4))

def download_design(design_id_or_code: DesignId, partial=False):
	if isinstance(design_id_or_code, str):
		design_id_ = design_id(design_id_or_code)
	else:
		design_id_ = design_id_or_code

	resp = acnh().request('GET', '/api/v2/designs', params={
		'offset': 0,
		'limit': 1,
		'q[design_id]': design_id_,
	})
	resp.raise_for_status()
	resp = msgpack.loads(resp.content)

	if not resp['total']:
		raise UnknownDesignCodeError
	if resp['total'] > 1:
		raise RuntimeError('one ID requested, but more than one returned?!')
	headers = resp['headers'][0]
	if partial:
		return headers

	url = urllib.parse.urlparse(headers['body'])
	resp = acnh().request('GET', url.path + '?' + url.query)
	data = msgpack.loads(resp.content)
	data['author_name'] = headers['design_player_name']
	data['author_id'] = headers['design_player_id']
	data['created_at'] = headers['created_at']
	data['updated_at'] = headers['updated_at']
	return data

def list_designs(author_id: int, *, pro: bool):
	resp = acnh().request('GET', '/api/v2/designs', params={
		'offset': 0,
		'limit': 120,
		'q[player_id]': author_id,
		'q[pro]': 'true' if pro else 'false',
		'with_binaries': 'true',
	})
	resp.raise_for_status()
	resp = msgpack.loads(resp.content)
	return resp

def delete_design(design_id_or_code) -> None:
	if isinstance(design_id_or_code, str):
		design_id_ = design_id(design_id_or_code)
	else:
		design_id_ = design_id_or_code

	resp = acnh().request('DELETE', '/api/v1/designs/' + str(design_id_))
	if resp.status_code == HTTPStatus.NOT_FOUND:
		raise UnknownDesignCodeError

def create_design(design_data) -> int:
	"""create a design. returns the created design ID."""
	resp = acnh().request('POST', '/api/v1/designs', data=msgpack.dumps(design_data))
	if resp.status_code == HTTPStatus.BAD_REQUEST:
		raise InvalidDesignError
	resp.raise_for_status()
	data = msgpack.loads(resp.content)
	print(data)
	return data['id']
