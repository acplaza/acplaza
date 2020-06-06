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

import datetime as dt
import enum
import logging
import re
import urllib.parse
from typing import ClassVar
from http import HTTPStatus

import msgpack
import toml
import requests

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

def authenticate_aauth():
	dauth = DAuthClient(keys)
	dauth.set_certificate(cert, pkey)
	dauth.set_system_version(SYSTEM_VERSION)
	device_token = load_cached('tokens/dauth-token.txt', lambda: dauth.device_token()['device_auth_token'])

	aauth = AAuthClient()
	aauth.set_system_version(SYSTEM_VERSION)
	app_token = load_cached('tokens/aauth-token.txt', lambda: aauth.auth_digital(
		ACNH.TITLE_ID, ACNH.TITLE_VERSION,
		device_token, ticket
	)['application_auth_token'])

	baas = BAASClient()
	baas.set_system_version(SYSTEM_VERSION)

	def get_id_token():
		baas.authenticate(device_token)
		response = baas.login(config['baas-user-id'], config['baas-password'], app_token)
		return toml.dumps({'user-id': int(response['user']['id'], base=16), 'id-token': response['idToken']})

	resp = toml.loads(load_cached('tokens/id-token.txt', get_id_token, duration=3 * 60 * 60))
	return resp['user-id'], resp['id-token']

def authenticate_acnh(id_token):
	acnh = ACNHClient(id_token)

	def get_app_token():
		resp = acnh.request('POST', '/api/v1/auth_token', data=msgpack.dumps({
			'id': config['acnh-user-id'],
			'password': config['acnh-password'],
		}))
		resp.raise_for_status()
		return resp.content

	resp = msgpack.loads(load_cached(
		'tokens/acnh-token.msgpack',
		get_app_token,
		duration=6 * 60 * 60,
		binary=True,
	))
	return resp['token']

def connect_backend(user_id, id_token):
	backend = BackEndClient(backend_settings)
	backend.configure(ACNH.ACCESS_KEY, ACNH.NEX_VERSION, ACNH.CLIENT_VERSION)

	# connect to game server
	backend.connect(HOST, PORT)

	# log in on game server
	auth_info = AuthenticationInfo()
	auth_info.token = id_token
	auth_info.ngs_version = 4  # Switch
	auth_info.token_type = 2
	backend.login(str(user_id), auth_info=auth_info)

	return backend
