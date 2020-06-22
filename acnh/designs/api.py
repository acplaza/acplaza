# © 2020 io mintz <io@mintz.cc>

import urllib.parse
from http import HTTPStatus
from functools import wraps
from typing import Union

import msgpack

from .. import utils
from ..errors import (
	UnknownDesignCodeError,
	InvalidDesignCodeError,
	UnknownAuthorIdError,
	InvalidAuthorIdError,
	InvalidDesignError,
)

DesignId = Union[str, int]

DESIGN_CODE_ALPHABET = InvalidDesignCodeError.DESIGN_CODE_ALPHABET
DESIGN_CODE_ALPHABET_VALUES = InvalidDesignCodeError.DESIGN_CODE_ALPHABET_VALUES

def design_id(design_code):
	code = design_code.replace('-', '')
	n = 0
	for c in code:
		n *= 30
		n += DESIGN_CODE_ALPHABET_VALUES[c]
	return n

def design_code(design_id):
	digits = []
	while design_id:
		design_id, digit = divmod(design_id, 30)
		digits.append(DESIGN_CODE_ALPHABET[digit])

	return add_hyphens(''.join(reversed(digits)).zfill(4 * 3))

def add_hyphens(author_id: str):
	return '-'.join(utils.chunked(author_id.zfill(4 * 3), 4))

def merge_headers(data, headers):
	data['author_name'] = headers['design_player_name']
	data['author_id'] = headers['design_player_id']
	data['created_at'] = headers['created_at']
	data['updated_at'] = headers['updated_at']

def download_design(design_id_or_code: DesignId, partial=False):
	if isinstance(design_id_or_code, str):
		design_id_ = design_id(InvalidDesignCodeError.validate(design_id_or_code))
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
	merge_headers(data, headers)
	return data

def list_designs(author_id: int, *, pro: bool, with_binaries: bool = False):
	resp = acnh().request('GET', '/api/v2/designs', params={
		'offset': 0,
		'limit': 120,
		'q[player_id]': author_id,
		'q[pro]': 'true' if pro else 'false',
		'with_binaries': 'true' if with_binaries else 'false',
	})
	resp.raise_for_status()
	resp = msgpack.loads(resp.content)
	return resp

def delete_design(design_id_or_code) -> None:
	if isinstance(design_id_or_code, str):
		design_id_ = design_id(InvalidDesignCodeError.validate(design_id_or_code))
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
	return data['id']
