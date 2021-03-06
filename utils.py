# © 2020 io mintz <io@mintz.cc>

import asyncio
import base64
import contextlib
import datetime as dt
import json
import secrets
import subprocess
import os
import sys
import urllib.parse

import flask.json
import jinja2
import wand.image
import toml
import asyncpg
import syncpg
from flask import current_app, g, request, session, url_for
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter

from acnh.errors import ACNHError, MissingUserAgentStringError, IncorrectAuthorizationError

# config comes first to resolve circular imports
with open('config.toml') as f:
	config = toml.load(f)

num_reverse_proxies = config.get('num-reverse-proxies', 1)

def get_ipaddr():
	if request.access_route:
		return request.access_route[-num_reverse_proxies]
	return request.remote_addr or '127.0.0.1'

def limiter_key():
	with contextlib.suppress(KeyError):
		return session['user_id']

	with contextlib.suppress(AttributeError):
		return request.user_id

	return get_ipaddr()

limiter = Limiter(key_func=limiter_key)

if os.name != 'nt':
	# this is pretty gay but it's necessary to make uwsgi work since sys.executable is uwsgi otherwise
	sys.executable = subprocess.check_output('which python3', shell=True, encoding='utf-8').rstrip()

def init_app(app):
	csrf = CSRFProtect(app)
	import views.api  # resolve circular import
	csrf.exempt(views.api.bp)
	app.secret_key = config['flask-secret-key']
	app.config['JSON_SORT_KEYS'] = False
	app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
	app.json_encoder = CustomJSONEncoder
	app.teardown_appcontext(close_pgconn)
	app.before_request(process_authorization)
	app.errorhandler(ACNHError)(handle_acnh_exception)
	limiter.init_app(app)
	token_exempt(app.send_static_file)

def pg():
	with contextlib.suppress(AttributeError):
		return g.pg

	asyncio.set_event_loop(asyncio.new_event_loop())
	pg = syncpg.connect(**config['postgres-db'])
	g.pg = pg
	return pg

token_exempt_views = set()

def token_exempt(view):
	token_exempt_views.add(view.__module__ + '.' + view.__name__)
	return view

def process_authorization():
	request.user_id = None

	if not request.endpoint:
		return

	view = current_app.view_functions.get(request.endpoint)
	dest = view.__module__ + '.' + view.__name__
	if dest in token_exempt_views:
		return

	if not request.headers.get('User-Agent'):
		raise MissingUserAgentStringError

	user_id = session.get('user_id')
	if user_id:
		if not request.user_id:
			request.user_id = session['user_id']
		return

	token = request.headers.get('Authorization')
	if not token:
		raise IncorrectAuthorizationError(request.full_path.rstrip('?'))

	user_id = validate_token(token)
	if not user_id:
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

	return user_id

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

	def default(self, o):
		if isinstance(o, bytes):
			return base64.b64encode(o).decode()
		if isinstance(o, dt.datetime):
			return o.replace(tzinfo=dt.timezone.utc).isoformat()
		if isinstance(o, asyncpg.Record):
			return dict(o)
		return super().default(o)

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

def handle_acnh_exception(ex):
	"""Return JSON instead of HTML for ACNH errors"""
	d = ex.to_dict()
	response = current_app.response_class()
	response.status_code = d['http_status']
	response.data = json.dumps(d)
	response.content_type = 'application/json'
	return response

def stream_template(template_name, **context):
	current_app.update_template_context(context)
	t = current_app.jinja_env.get_template(template_name)
	rv = t.stream(context)
	rv.disable_buffering()
	return current_app.response_class(rv)

def is_safe_url(target, *, _allowed_schemes=frozenset({'http', 'https'})):
	ref_url = urllib.parse.urlparse(request.host_url)
	test_url = urllib.parse.urlparse(urllib.parse.urljoin(request.host_url, target))
	return (
		test_url.scheme in _allowed_schemes
		and ref_url.netloc == test_url.netloc
		and test_url.path != url_for('.login')
	)

def get_redirect_target():
	for target in request.values.get('next'), request.referrer:
		if not target:
			continue
		if is_safe_url(target):
			return target
