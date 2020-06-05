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

import msgpack
from nintendo.common.http import HTTPRequest

from .common import config, authenticate_aauth, authenticate_acnh, ACNHError, InvalidFormatError, ACNHClient

class DesignCodeError(ACNHError):
	pass

class UnknownDesignCodeError(DesignCodeError):
	code = 21
	message = 'unknown design code'
	http_status = HTTPStatus.BAD_REQUEST

_design_code_alphabet = '0123456789BCDFGHJKLMNPQRSTVWXY'
DESIGN_CODE_ALPHABET = {c: val for val, c in enumerate(_design_code_alphabet)}

class InvalidDesignCodeError(DesignCodeError, InvalidFormatError):
	code = 22
	message = 'invalid design code'
	_design_code_segment = f'[{_design_code_alphabet}]{{4}}'
	regex = re.compile('-'.join([_design_code_segment] * 3))
	del _design_code_segment

def design_id(pattern_code):
	code = pattern_code.replace('-', '')
	n = 0
	for c in code:
		n *= 30
		try:
			n += DESIGN_CODE_ALPHABET[c]
		except KeyError:
			raise InvalidDesignCodeError
	return n

def _download_design(token, design_code):
	acnh = ACNHClient(token)
	resp = acnh.request('GET', '/api/v2/designs', params={
		'offset': '0',
		'limit': '40',
		'q[design_id]': str(design_id(design_code)),
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

def download_design(design_code):
	InvalidDesignCodeError.validate(design_code)

	_, id_token = authenticate_aauth()
	token = authenticate_acnh(id_token)
	return _download_design(token, design_code)
