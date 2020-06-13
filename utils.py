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
from werkzeug.exceptions import HTTPException

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
	app.errorhandler(HTTPException)(handle_exception)
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

class IncorrectAuthorizationHeader(AuthorizationError):
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
		raise IncorrectAuthorizationHeader

	if not validate_token(token):
		raise IncorrectAuthorizationHeader

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
	return base64.b64encode(user_id.to_bytes(4, byteorder='big')).decode() + '.' + base64.b64encode(secret).decode()

def parse_token(token):
	id, secret = token.encode().split(b'.')
	# big endian is used cause it's easier to read at a glance
	return int.from_bytes(base64.b64decode(id), byteorder='big'), base64.b64decode(secret)

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

def handle_exception(ex):
	"""Return JSON instead of HTML for HTTP errors."""
	# start with the correct headers and status code from the error
	response = ex.get_response()
	# replace the body with JSON
	response.data = json.dumps({
		'http_status': ex.code,
		'http_status_name': ex.name,
		'http_status_description': ex.description,
	})
	response.content_type = 'application/json'
	return response

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
