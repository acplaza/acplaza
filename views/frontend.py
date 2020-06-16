#!/usr/bin/env python3

import datetime as dt
from http import HTTPStatus

from flask import Blueprint, render_template, session, request, redirect, url_for

import utils
from views import api
from acnh.common import ACNHError
from acnh.designs import api as designs_api
from acnh.designs import render as designs_render

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

bp.route('/design/<design_code>/<layer>.png')(api.design_layer)

@bp.route('/design/<design_code>')
def design(design_code):
	data = designs_api.download_design(designs_api.design_id(design_code))
	meta, body = data['mMeta'], data['mData']
	type_code = meta['mMtUse']
	design_name = meta['mMtDNm']

	layers = designs_render.render_external_layers(body, type_code)
	images = (
		(name.capitalize().replace('-', ' '), utils.image_to_base64_url(utils.xbrz_scale_wand_in_subprocess(image, 6)))
		for name, image
		in designs_render.render_external_layers(body, type_code).items()
	)

	return render_template(
		'design.html',
		created_at=dt.datetime.utcfromtimestamp(data['created_at']),
		author_name=data['author_name'],
		author_id=data['author_id'],
		design_name=design_name,
		island_name=meta['mMtVNm'],
		layers=images,
	)

@bp.errorhandler(ACNHError)
def handle_acnh_exception(ex):
	return render_template('error.html', message=ex.message), ex.http_status

@bp.errorhandler(utils.IncorrectAuthorizationError)
def handle_not_logged_in(ex):
	return redirect(url_for('.login'))
