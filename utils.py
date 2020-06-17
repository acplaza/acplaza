# © 2020 io mintz <io@mintz.cc>

import asyncio
import base64
import contextlib
import datetime as dt
import io
import pickle
import json
import secrets
import subprocess
import os
import sys
from http import HTTPStatus

import flask.json
import jinja2
import wand.image
import toml
import asyncpg
import syncpg
from flask import current_app, g, request, session
from flask_limiter.util import get_ipaddr
from flask_wtf.csrf import CSRFProtect

# config comes first to resolve circular imports
with open('config.toml') as f:
	config = toml.load(f)

if os.name != 'nt':
	# this is pretty gay but it's necessary to make uwsgi work since sys.executable is uwsgi otherwise
	sys.executable = subprocess.check_output('which python3', shell=True, encoding='utf-8').rstrip()

from acnh.common import ACNHError

def init_app(app):
	CSRFProtect(app)
	app.secret_key = config['flask-secret-key']
	app.config['JSON_SORT_KEYS'] = False
	app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
	app.json_encoder = CustomJSONEncoder
	app.teardown_appcontext(close_pgconn)
	app.before_request(process_authorization)

def pg():
	with contextlib.suppress(AttributeError):
		return g.pg

	asyncio.set_event_loop(asyncio.new_event_loop())
	pg = syncpg.connect(**config['postgres-db'])
	g.pg = pg
	return pg

class AuthorizationError(ACNHError):
	pass

class MissingUserAgentStringError(AuthorizationError):
	code = 91
	message = 'User-Agent header required'
	http_status = HTTPStatus.BAD_REQUEST

class IncorrectAuthorizationError(AuthorizationError):
	code = 92
	message = 'invalid or incorrect Authorization header'
	http_status = HTTPStatus.UNAUTHORIZED

token_exempt_views = set()

def token_exempt(view):
	token_exempt_views.add(view.__module__ + '.' + view.__name__)
	return view

def process_authorization():
	request.user_id = None
	session.setdefault('authed', False)

	if get_ipaddr() == '127.0.0.1':
		return

	if not request.endpoint:
		return

	view = current_app.view_functions.get(request.endpoint)
	dest = view.__module__ + '.' + view.__name__
	if dest in token_exempt_views:
		return

	if not request.headers.get('User-Agent'):
		raise MissingUserAgentStringError

	if session['authed']:
		return

	token = request.headers.get('Authorization')
	if not token:
		raise IncorrectAuthorizationError

	if not validate_token(token):
		raise IncorrectAuthorizationError

	request.user_id = user_id

def validate_token(token):
	try:
		user_id, secret = parse_token(token)
	except ValueError:
		return False

	db_secret = pg().fetchval(queries.secret(), user_id)
	if db_secret is None:
		return False

	if not secrets.compare_digest(secret, db_secret):
		return False

	return True

def encode_token(user_id, secret):
	left = str(user_id)
	right = base64.urlsafe_b64encode(secret).rstrip(b'=').decode('ascii')
	return left + '.' + right

def parse_token(token):
	id, secret = token.encode().split(b'.')
	# restore padding
	secret += b'=' * (-len(secret) % 4)
	return int(id), base64.urlsafe_b64decode(secret)

def close_pgconn(_):
	with contextlib.suppress(AttributeError):
		g.pg.close()

queries = jinja2.Environment(
	loader=jinja2.FileSystemLoader('.'),
	line_statement_prefix='-- :',
).get_template('queries.sql').module

class CustomJSONEncoder(flask.json.JSONEncoder):
	def __init__(self, **kwargs):
		kwargs['ensure_ascii'] = False
		super().__init__(**kwargs)

	def default(self, x):
		if isinstance(x, bytes):
			return base64.b64encode(x).decode()
		if isinstance(x, dt.datetime):
			return x.replace(tzinfo=dt.timezone.utc).isoformat()
		if isinstance(x, asyncpg.Record):
			return dict(x)
		return super().default(x)

def xbrz_scale_wand_in_subprocess(img: wand.image.Image, factor):
	data = bytearray(img.export_pixels(channel_map='RGBA', storage='char'))

	p = subprocess.Popen(
		[sys.executable, '-m', 'xbrz', *map(str, (factor, *img.size))],
		stdin=subprocess.PIPE,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
	)
	stdout, stderr = p.communicate(data)
	if stderr and p.returncode:
		raise RuntimeError(stderr.decode('utf-8'))

	scaled = wand.image.Image(width=img.width * factor, height=img.height * factor)
	scaled.import_pixels(channel_map='RGBA', storage='char', data=stdout)
	return scaled

def image_to_base64_url(img: wand.image.Image):
	return (b'data:image/png;base64,' + base64.b64encode(img.make_blob('png'))).decode()
