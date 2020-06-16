#!/usr/bin/env python3

import datetime as dt
from http import HTTPStatus

import msgpack
from flask import Blueprint, render_template, session, request, redirect, url_for

import utils
from views import api
from acnh.common import ACNHError, acnh
from acnh.designs import api as designs_api
from acnh.designs import render as designs_render
from acnh.designs import encode as designs_encode

def init_app(app):
	app.register_blueprint(bp)

bp = Blueprint('frontend', __name__)

@bp.route('/login')
@utils.token_exempt
def login_form():
	return render_template('login.html')

@bp.route('/login', methods=['POST'])
@utils.token_exempt
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
	return 'OK'

@bp.route('/design/')
def design_form():
	try:
		return redirect(url_for('.design', design_code=request.args['design_code']))
	except KeyError:
		return render_template('design_form.html', design_code_regex=designs_api.InvalidDesignCodeError.regex.pattern)

@bp.route('/designs/')
def designs_form():
	try:
		return redirect(url_for('.basic_designs', author_id=request.args['author_id']))
	except KeyError:
		return render_template('designs_form.html', author_id_regex=designs_api.InvalidAuthorIdError.regex.pattern)

bp.route('/design/<design_code>/<layer>.png')(api.design_layer)
bp.route('/design/<design_code>.tar')(api.design_archive)

@bp.route('/design/<design_code>')
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
def basic_designs(author_id):
	return designs(author_id, pro=False)

@bp.route('/pro-designs/<author_id>')
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

@bp.errorhandler(ACNHError)
def handle_acnh_exception(ex):
	return render_template('error.html', message=ex.message), ex.http_status

@bp.errorhandler(utils.IncorrectAuthorizationError)
def handle_not_logged_in(ex):
	return redirect(url_for('.login'))
