import re

import msgpack
from nintendo.common.http import HTTPRequest

from .common import config, authenticate_aauth, authenticate_app, ACNHError, InvalidFormatMixin, ACNHClient

class DesignCodeError(ACNHError):
	pass

class UnknownDesignCodeError(DesignCodeError):
	code = 21
	message = 'unknown design code'

_design_code_segment = '[0-9BCDFGHJKLMNPQRSTVWXY]{4}'
DESIGN_CODE_RE = re.compile('\\-'.join([_design_code_segment] * 4))

class InvalidDesignCodeError(DesignCodeError, InvalidFormatMixin):
	code = 22
	message = 'invalid design code'
	regex = DESIGN_CODE_RE.pattern

DESIGN_CODE_ALPHABET = {c: i for i, c in enumerate('0123456789BCDFGHJKLMNPQRSTVWXY')}

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
	req = HTTPRequest.get('/api/v2/designs')
	req.params['offset'] = '0'
	req.params['limit'] = '40'
	req.params['q[design_id]'] = str(design_id(design_code))
	print(acnh.request(req).body)
	resp = msgpack.loads(acnh.request(req).body)

	if not resp['total']:
		raise UnknownDesignCodeError
	if resp['total'] > 1:
		raise RuntimeError('one ID requested, but more than one returned?!')
	headers = resp['headers'][0]

	url = urllib.parse.urlparse(headers['body'])
	req = HTTPRequest.get(url.path + '?' + url.query)
	return msgpack.loads(acnh.request(req).body)

def download_design(design_code):
	_, id_token = authenticate_aauth()
	token = authenticate_app(id_token)
	return _download_design(token, design_code)
