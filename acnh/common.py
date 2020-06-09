# © 2020 io mintz <io@mintz.cc>

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
import datetime as dt
import enum
import functools
import logging
import re
import urllib.parse
from typing import ClassVar
from http import HTTPStatus

import msgpack
import toml
import requests
from flask import g, request

from nintendo.baas import BAASClient
from nintendo.dauth import DAuthClient
from nintendo.aauth import AAuthClient
from nintendo.switch import ProdInfo, KeySet, TicketList
from nintendo.nex.backend import BackEndClient
from nintendo.nex.authentication import AuthenticationInfo
from nintendo.nex import matchmaking
from nintendo.games import ACNH
from nintendo.settings import Settings

from .utils import load_cached

SYSTEM_VERSION = 1003  # 10.0.3
HOST = 'g%08x-lp1.s.n.srv.nintendo.net' % ACNH.GAME_SERVER_ID
PORT = 443

with open('config.toml') as f:
	config = toml.load(f)

keys = KeySet(config['keyset-path'])
prodinfo = ProdInfo(keys, config['prodinfo-path'])

cert = prodinfo.get_ssl_cert()
pkey = prodinfo.get_ssl_key()

with open(config['ticket-path'], 'rb') as f:
	ticket = f.read()

backend_settings = Settings('switch.cfg')

class ACNHError(Exception):
	code: ClassVar[int]
	message: ClassVar[str]
	http_status: ClassVar[int]

	def __int__(self):
		return self.code

	def to_dict(self):
		return {'error': self.message, 'error_code': self.code, 'http_status': self.http_status}

class InvalidFormatError(ACNHError):
	http_status = HTTPStatus.BAD_REQUEST
	regex: re.Pattern

	def to_dict(self):
		d = super().to_dict()
		d['validation_regex'] = self.regex.pattern
		return d

	@classmethod
	def validate(cls, s):
		if not cls.regex.fullmatch(s):
			raise cls

class ACNHClient:
	BASE = 'https://api.hac.lp1.acbaa.srv.nintendo.net'
	HEADERS = {
		'User-Agent': 'libcurl/7.64.1 (HAC; nnEns; SDK 9.3.4.0)',
		'Host': urllib.parse.urlparse(BASE).netloc,
		'Accept': '*/*',
	}
	# note: OPTIONS can technically have an request body, but it's not specified what that means,
	# and ACNH doesn't use OPTIONS anyway
	REQUEST_METHODS_WITH_BODIES = frozenset({'POST', 'PUT'})

	def __init__(self, token):
		self.token = token
		self.session = requests.Session()
		self.session.headers.clear()
		self.session.headers.update(self.HEADERS)
		self.session.headers['Authorization'] = 'Bearer ' + token
		self.session.verify = 'data/nintendo-ca.crt'

	def request(self, method, path, **kwargs):
		headers = {}
		if method in self.REQUEST_METHODS_WITH_BODIES:
			headers['Content-Type'] = 'application/x-msgpack'
		return self.session.request(method, self.BASE + path, headers=headers, **kwargs)

	def __enter__(self):
		return self.session.__enter__()

	def __exit__(self, *excinfo):
		return self.session.__exit__(*excinfo)

	def close(self):
		self.session.close()

def init_app(app):
	app.teardown_appcontext(close_clients)
	app.after_request(close_backend)

gfuncs = []

def close_clients(_):
	for f in gfuncs:
		with contextlib.suppress(AttributeError):
			getattr(g, f.__name__).close()

def gfunc(func):
	@functools.wraps(func)
	def wrapped():
		try:
			return getattr(g, func.__name__)
		except AttributeError:
			rv = func()
			setattr(g, func.__name__, rv)
			return rv

	gfuncs.append(wrapped)
	return wrapped

@gfunc
def dauth():
	dauth = DAuthClient(keys)
	dauth.set_certificate(cert, pkey)
	dauth.set_system_version(SYSTEM_VERSION)
	return dauth

@gfunc
def aauth():
	aauth = AAuthClient()
	aauth.set_system_version(SYSTEM_VERSION)
	return aauth

@gfunc
def baas():
	baas = BAASClient()
	baas.set_system_version(SYSTEM_VERSION)
	baas.authenticate(device_token())
	return baas

@gfunc
def acnh():
	_, id_token = baas_credentials()
	acnh = ACNHClient(id_token)
	acnh_token_ = acnh_token(acnh)
	try:
		return ACNHClient(acnh_token_)
	finally:
		acnh.close()

def backend():
	with contextlib.suppress(AttributeError):
		return request.backend

	backend = BackEndClient(backend_settings)
	backend.configure(ACNH.ACCESS_KEY, ACNH.NEX_VERSION, ACNH.CLIENT_VERSION)

	# connect to game server
	backend.connect(HOST, PORT)

	# log in on game server
	user_id, id_token = baas_credentials()
	auth_info = AuthenticationInfo()
	auth_info.token = id_token
	auth_info.ngs_version = 4  # Switch
	auth_info.token_type = 2
	backend.login(str(user_id), auth_info=auth_info)

	request.backend = backend
	return backend

def close_backend(response):
	with contextlib.suppress(AttributeError):
		request.backend.close()

def device_token():
	return load_cached('tokens/dauth-token.txt', lambda: dauth().device_token()['device_auth_token'])

def aauth_token():
	return load_cached('tokens/aauth-token.txt', lambda: aauth().auth_digital(
		ACNH.TITLE_ID, ACNH.TITLE_VERSION,
		device_token(), ticket
	)['application_auth_token'])

def baas_credentials():
	def get_credentials():
		print('baas credentials')
		resp = baas().login(config['baas-user-id'], config['baas-password'], aauth_token())
		return toml.dumps({'user-id': int(resp['user']['id'], base=16), 'id-token': resp['idToken']})

	resp = toml.loads(load_cached('tokens/baas-credentials.txt', get_credentials, duration=3 * 60 * 60))
	return resp['user-id'], resp['id-token']

def acnh_token(acnh):
	def get_acnh_token():
		print('acnh token')
		resp = acnh.request('POST', '/api/v1/auth_token', data=msgpack.dumps({
			'id': config['acnh-user-id'],
			'password': config['acnh-password'],
		}))
		resp.raise_for_status()
		return resp.content

	resp = msgpack.loads(load_cached(
		'tokens/acnh-token.msgpack',
		get_acnh_token,
		duration=6 * 60 * 60,
		binary=True,
	))
	return resp['token']
