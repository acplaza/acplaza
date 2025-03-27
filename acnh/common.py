# © io

# Based on code provided by Yannik Marchand under the MIT License.
# Copyright (c) 2017 Yannik Marchand

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import contextlib
import functools
import urllib.parse
import ssl

import msgpack
import qtoml as toml
#import requests
from quart import current_app, g, request
import anynet.http
import anynet.tls

from nintendo.switch.baas import BAASClient
from nintendo.switch.dauth import DAuthClient, CLIENT_ID_DRAGONS, CLIENT_ID_BAAS
from nintendo.switch.aauth import AAuthClient
from nintendo.switch.dragons import DragonsClient
from nintendo.switch import load_keys
from nintendo.nex import settings
from nintendo.nex.backend import BackEndClient
from nintendo.nex.authentication import AuthenticationInfo

from .utils import load_cached

def init_app(app):
	app.while_serving(acnh)

# this is here to resolve circular imports
# pylint: disable=wrong-import-position
from utils import config

TITLE_ID = 0x01006F8002326000
TITLE_VERSION = 0x1C0000

SYSTEM_VERSION = 1901  # 19.0.1
GAME_SERVER_ID = 0x2EE2E300
NEX_VERSION = 40604
CLIENT_VERSION = 2
ACCESS_KEY = 'v43a10em'
HOST = 'g%08x-lp1.s.n.srv.nintendo.net' % GAME_SERVER_ID
CLIENT_VERSION = 2
PORT = 443

keys = load_keys(config['keyset-path'])

with open(config['device-cert-path']) as f:
	cert = anynet.tls.TLSCertificate.parse(f.read(), anynet.tls.TYPE_PEM)

with open(config['device-key-path']) as f:
	pkey = anynet.tls.TLSPrivateKey.parse(f.read(), anynet.tls.TYPE_PEM)

class ACNHClient:
	BASE = 'https://api.hac.lp1.acbaa.srv.nintendo.net'
	HEADERS = {
		'Host': urllib.parse.urlparse(BASE).netloc,
		'User-Agent': 'libcurl/7.64.1 (HAC; nnEns; SDK 10.9.8.0)',
		'Accept': '*/*',
	}
	# note: OPTIONS can technically have an request body, but it's not specified what that means,
	# and ACNH doesn't use OPTIONS anyway
	REQUEST_METHODS_WITH_BODIES = frozenset({'POST', 'PUT'})

	def __init__(self, token):
		self.token = token
		self.headers = self.HEADERS.copy()
		self.headers['Authorization'] = 'Bearer ' + token

	async def request(self, request):
		# allow fetching host-free URLs
		if not request.path.startswith(self.BASE):
			request.path = self.BASE + request.path
		request.headers.update(self.headers)
		if request.method in self.REQUEST_METHODS_WITH_BODIES:
			request.headers['Content-Type'] = 'application/x-msgpack'

		return await self.http_client.request(request)

	async def __aenter__(self):
		ctx = anynet.tls.TLSContext()
		ctx.set_authority(anynet.tls.TLSCertificate.load('data/nintendo-ca.crt', anynet.tls.TYPE_PEM))
		self._ctxman = anynet.http.connect(self.BASE, ctx)
		self.http_client = await self._ctxman.__aenter__()
		return self

	async def __aexit__(self, *excinfo):
		return await self._ctxman.__aexit__(*excinfo)

def appfunc(func):
	@functools.wraps(func)
	async def wrapped():
		try:
			return getattr(current_app, func.__name__)
		except AttributeError:
			rv = await func()
			setattr(current_app, func.__name__, rv)
			return rv

	return wrapped

@appfunc
async def dauth():
	dauth = DAuthClient(keys)
	dauth.set_certificate(cert, pkey)
	dauth.set_system_version(SYSTEM_VERSION)
	return dauth

@appfunc
async def dragons():
	dragons = DragonsClient()
	dragons.set_certificate(cert, pkey)
	dragons.set_system_version(SYSTEM_VERSION)
	return dragons

@appfunc
async def aauth():
	aauth = AAuthClient()
	aauth.set_system_version(SYSTEM_VERSION)
	return aauth

@appfunc
async def baas():
	baas = BAASClient()
	baas.set_system_version(SYSTEM_VERSION)
	#await baas.authenticate(device_token())
	return baas

async def acnh():
	_, id_token = await baas_credentials()
	acnh_token_ = await acnh_token(id_token)
	async with ACNHClient(acnh_token_) as current_app.acnh:
		yield

def backend():
	raise NotImplementedError

async def device_token_dragons():
	async def cb(): return (await (await dauth()).device_token(CLIENT_ID_DRAGONS))['device_auth_token']
	return await load_cached('tokens/dauth-dragons.txt', cb)

async def device_token_baas():
	async def cb(): return (await (await dauth()).device_token(CLIENT_ID_BAAS))['device_auth_token']
	return await load_cached('tokens/dauth-baas.txt', cb)

async def contents_token():
	async def cb(): return (await (await dragons()).contents_authorization_token_for_aauth(
		await device_token_dragons(),
		config['elicense-id'],
		config['na-id'],
		TITLE_ID,
	))['contents_authorization_token']
	return await load_cached('tokens/contents-token.txt', cb)

async def aauth_token():
	async def cb(): return (await (await aauth()).auth_digital(TITLE_ID, TITLE_VERSION, await device_token_baas(), await contents_token()))['application_auth_token']
	return await load_cached('tokens/aauth-token.txt', cb)

async def anonymous_baas_credentials():
	async def cb(): return (await (await baas()).authenticate(await device_token_baas(), config['penne-id']))['accessToken']
	return await load_cached('tokens/anonymous-baas.txt', cb)

async def baas_credentials():
	async def get_credentials():
		resp = await (await baas()).login(config['baas-user-id'], config['baas-password'], await anonymous_baas_credentials(), await aauth_token(), config['na-country'])
		return toml.dumps({'user-id': int(resp['user']['id'], base=16), 'id-token': resp['idToken']})

	resp = toml.loads(await load_cached('tokens/baas-credentials.txt', get_credentials, duration=2.5 * 60 * 60))
	return resp['user-id'], resp['id-token']

async def acnh_token(id_token):
	async def get_acnh_token():
		req = anynet.http.HTTPRequest.post('/api/v1/auth_token')
		req.body = msgpack.dumps({
			'id': config['acnh-user-id'],
			'password': config['acnh-password'],
		})
		async with ACNHClient(id_token) as acnh:
			resp = await acnh.request(req)
		resp.raise_if_error()
		return resp.body

	resp = msgpack.loads(await load_cached(
		'tokens/acnh-token.msgpack',
		get_acnh_token,
		duration=5 * 60 * 60,
		binary=True,
	))
	return resp['token']
