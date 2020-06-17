#!/usr/bin/env python3

import datetime as dt
from http import HTTPStatus

import msgpack
from flask import Blueprint, render_template, session, request, redirect, url_for, current_app, stream_with_context
from werkzeug.exceptions import HTTPException

import utils
from views import api
from acnh import dodo
from acnh.common import ACNHError, acnh
from acnh.designs import api as designs_api
from acnh.designs import render as designs_render
from acnh.designs import encode as designs_encode
from utils import limiter

def init_app(app):
	app.register_blueprint(bp)
	app.add_template_global(designs_api.InvalidDesignCodeError.regex.pattern, name='design_code_regex')
	app.add_template_global(designs_api.InvalidAuthorIdError.regex.pattern, name='author_id_regex')
	app.add_template_global(dodo.InvalidDodoCodeError.regex.pattern, name='dodo_code_regex')
	app.add_template_global(designs_encode.Design.categories, name='design_categories')

bp = Blueprint('frontend', __name__)

@bp.route('/login')
@utils.token_exempt
def login_form():
	return render_template('login.html')

@bp.route('/login', methods=['POST'])
@utils.token_exempt
@limiter.limit('1 per 5 seconds')
def login():
	try:
		token = request.form['token']
	except KeyError:
		# we don't need to have a fancy error class for this one because the user is intentionally fucking
		# with the form
		abort(HTTPStatus.UNAUTHORIZED)

	if not utils.validate_token(token):
		return 'auth failed', HTTPStatus.UNAUTHORIZED

	session['authed'] = 1
	return redirect('/')

@bp.route('/logout')
@utils.token_exempt
def logout():
	session.pop('authed', None)
	return redirect('/')

@bp.route('/')
def index():
	return render_template('index.html')

@bp.route('/host-session/')
def host_session_form():
	try:
		return redirect(url_for('.host_session', dodo_code=request.args['dodo_code']))
	except KeyError:
		return render_template('host_session_form.html')

@bp.route('/host-session/<dodo_code>')
@limiter.limit('1 per 4 seconds')
def host_session(dodo_code):
	data = dodo.search_dodo_code(dodo_code)
	return render_template('host_session.html', **data)

@bp.route('/design/')
def design_form():
	try:
		return redirect(url_for('.design', design_code=request.args['design_code']))
	except KeyError:
		return render_template('design_form.html')

@bp.route('/designs/')
def designs_form():
	try:
		return redirect(url_for('.basic_designs', author_id=request.args['author_id']))
	except KeyError:
		return render_template('designs_form.html')

bp.route('/design/<design_code>/<layer>.png')(api.design_layer)
bp.route('/design/<design_code>.tar')(api.design_archive)

@bp.route('/design/<design_code>')
@limiter.limit('2 per 10 seconds')
def design(design_code):
	data = designs_api.download_design(design_code)
	meta = data['mMeta']
	design_name = meta['mMtDNm']

	design = designs_encode.Design.from_data(data)

	images = (
		(name.capitalize().replace('-', ' '), utils.image_to_base64_url(utils.xbrz_scale_wand_in_subprocess(image, 6)))
		for name, image
		in design.layer_images.items()
	)

	return render_template(
		'design.html',
		created_at=dt.datetime.utcfromtimestamp(data['created_at']),
		author_name=data['author_name'],
		author_id=designs_api.add_hyphens(str(data['author_id'])),
		design_code=design_code,
		design_name=design_name,
		design_type=type(design).display_name,
		island_name=meta['mMtVNm'],
		layers=images,
	)

@bp.route('/designs/<author_id>')
@limiter.limit('5 per 25 seconds')
def basic_designs(author_id):
	return designs(author_id, pro=False)

@bp.route('/pro-designs/<author_id>')
@limiter.limit('5 per 25 seconds')
def pro_designs(author_id):
	return designs(author_id, pro=True)

def designs(author_id, *, pro):
	author_id = int(designs_api.InvalidAuthorIdError.validate(author_id).replace('-', ''))
	pretty_author_id = designs_api.add_hyphens(str(author_id))
	data = designs_api.list_designs(author_id, pro=pro, with_binaries=True)
	if not data['total']:
		return render_template(
			'no_designs.html',
			pro=pro, design_type='Pro' if pro else 'basic', author_id=pretty_author_id,
		)

	author_name = data['headers'][0]['design_player_name']

	designs = []
	for header in data['headers']:
		# XXX unfortunately this page is made a lot slower due to requesting each design just for its
		# design name. Our options aren't great though. We can either fetch each design on the client side,
		# or we can omit the design name entirely.
		data = msgpack.loads(acnh().request('GET', header['body']).content)
		designs_api.merge_headers(data, header)
		design_code = designs_api.design_code(header['id'])
		net_image = designs_encode.Design.from_data(data).net_image()
		designs.append((
			data['mMeta']['mMtDNm'],
			design_code,
			utils.image_to_base64_url(net_image),
		))

	return render_template(
		'designs.html',
		author_id=pretty_author_id,
		author_name=author_name,
		pro=pro,
		designs=designs,
		design_type='Pro' if pro else 'basic',
	)

@bp.route('/create-design')
def pick_design_type_form():
	return render_template('pick_design_type.html')

@bp.route('/create-design/basic-design')
def create_basic_design_form():
	return render_template('create_basic_design_form.html')

@bp.route('/create-design/<_>', methods=['POST'])
@limiter.limit('1 per 15 seconds')
def create_image(_):
	gen = stream_with_context(api._create_image())
	image_id = next(gen)
	def pretty_gen():
		for was_quantized, design_id in gen:
			yield was_quantized, designs_api.design_code(design_id)

	return current_app.response_class(
		utils.stream_template('created_image.html', image_id=image_id, results=pretty_gen())
	)

@bp.route('/create-design/<design_type_name>')
def create_pro_design_form(design_type_name):
	try:
		cls = designs_encode.Design(design_type_name)
	except KeyError:
		return redirect('/create-design')

	return render_template('create_design_form.html', cls=cls)

@bp.errorhandler(ACNHError)
def handle_acnh_exception(ex):
	d = ex.to_dict()
	return render_template('error.html', message=d['error']), d['http_status']

@bp.errorhandler(HTTPException)
def handle_http_exception(ex):
	return render_template('error.html', message=ex.name, description=ex.get_description())

@bp.errorhandler(utils.IncorrectAuthorizationError)
def handle_not_logged_in(ex):
	return redirect(url_for('.login'))
