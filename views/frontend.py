#!/usr/bin/env python3

import datetime as dt
from http import HTTPStatus

import msgpack
import wand.image
from flask import (
	abort,
	Blueprint,
	render_template,
	session,
	request,
	redirect,
	url_for,
	stream_with_context,
	flash,
)
from werkzeug.exceptions import HTTPException

import utils
from views import api
from acnh import dodo
from acnh.common import acnh
from acnh.errors import (
	ACNHError,
	InvalidAuthorIdError,
	InvalidDesignCodeError,
	InvalidDodoCodeError,
	IncorrectAuthorizationError,
)
from acnh.designs import api as designs_api
from acnh.designs import encode as designs_encode
from acnh.designs import db as designs_db
from acnh.designs.format import MAX_DESIGN_TILES
from utils import limiter

def init_app(app):
	app.register_blueprint(bp)
	app.add_template_global(utils.config['acnh-design-creator-id'], name='api_author_id')
	app.add_template_global(
		"This design had to be quantized to fit the game's 16 color limit.",
		name='quantized_message',
	)
	app.add_template_global(__import__('time').sleep)

bp = Blueprint('frontend', __name__)

@bp.route('/about')
@utils.token_exempt
def about():
	return render_template('about.html')

@bp.route('/login')
@utils.token_exempt
def login_form():
	if session.get('user_id'):
		return redirect('/')
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

	user_id = utils.validate_token(token)
	if not user_id:
		return 'auth failed', HTTPStatus.UNAUTHORIZED

	session['user_id'] = user_id

	target = utils.get_redirect_target()
	if target:
		return redirect(target)

	return redirect('/')

@bp.route('/logout')
@utils.token_exempt
def logout():
	session.clear()
	return redirect('/')

@bp.route('/')
@utils.token_exempt
def index():
	if not session.get('user_id'):
		return redirect(url_for('.login'))
	# pylint: disable=no-member
	return render_template(
		'index.html',
		design_code_regex=InvalidDesignCodeError.regex.pattern,
		author_id_regex=InvalidAuthorIdError.regex.pattern,
		dodo_code_regex=InvalidDodoCodeError.regex.pattern,
	)

@bp.route('/host-session/')
def host_session_form():
	try:
		return redirect(url_for('.host_session', dodo_code=request.args['dodo_code']))
	except KeyError:
		return redirect('/')

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
		return redirect('/')

@bp.route('/designs/')
def designs_form():
	try:
		return redirect(url_for('.basic_designs', author_id=request.args['author_id']))
	except KeyError:
		return redirect('/')

bp.route('/design/<design_code>/<layer>.png')(api.design_layer)
bp.route('/design/<design_code>.tar')(api.design_archive)
bp.route('/image/<image_id>.tar')(api.image_archive)

@bp.route('/design/<design_code>')
@limiter.limit('2 per 10 seconds')
def design(design_code):
	image_info = designs_db.design_image(design_code)
	if image_info and image_info['designs_required'] == 1:
		return redirect(url_for('.image', image_id=image_info['image_id']))

	data = designs_api.download_design(design_code)
	meta = data['mMeta']
	design_name = meta['mMtDNm']

	design = designs_encode.Design.from_data(data)

	def gen():
		for name, image in design.layer_images.items():
			yield (
				name.capitalize().replace('-', ' '),
				utils.image_to_base64_url(utils.xbrz_scale_wand_in_subprocess(image, 6)),
			)

	return utils.stream_template(
		'design.html',
		created_at=dt.datetime.utcfromtimestamp(data['created_at']),
		image_id=image_info and image_info['image_id'],
		author_name=data['author_name'],
		author_id=data['author_id'],
		pretty_author_id=designs_api.add_hyphens(str(data['author_id'])),
		design_code=design_code,
		design_name=design_name,
		design_type=type(design).display_name,
		island_name=meta['mMtVNm'],
		layers=stream_with_context(gen()),
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
	author_id = int(InvalidAuthorIdError.validate(author_id).replace('-', ''))
	pretty_author_id = designs_api.add_hyphens(str(author_id))
	data = designs_api.list_designs(author_id, pro=pro, with_binaries=True)
	if not data['total']:
		return render_template(
			'no_designs.html',
			pro=pro, design_type='Pro' if pro else 'basic', author_id=pretty_author_id,
		)

	author_name = data['headers'][0]['design_player_name']

	def designs():
		for header in data['headers']:
			design_data = msgpack.loads(acnh().request('GET', header['body']).content)
			designs_api.merge_headers(design_data, header)
			design_code = designs_api.design_code(header['id'])
			net_image = designs_encode.Design.from_data(design_data).net_image()
			yield (
				design_data['mMeta']['mMtDNm'],
				design_code,
				utils.image_to_base64_url(net_image),
			)

	return utils.stream_template(
		'designs.html',
		author_id=pretty_author_id,
		author_name=author_name,
		pro=pro,
		designs=stream_with_context(designs()),
		design_type='Pro' if pro else 'basic',
	)

@bp.route('/create-design')
def pick_design_type_form():
	return render_template('pick_design_type.html', design_categories=designs_encode.Design.categories)

@bp.route('/create-design/basic-design')
def create_basic_design_form():
	return render_template('create_basic_design_form.html')

@bp.route('/create-design/<_>', methods=['POST'])
@limiter.limit('1 per 15 seconds')
def create_image(_):
	gen = stream_with_context(api.create_image_gen())
	image_id = next(gen)
	return utils.stream_template(
		'created_image.html', image_id=image_id, results=format_created_designs_gen(gen), verb='created',
	)

def format_created_designs_gen(gen):
	for was_quantized, design_id in gen:
		yield was_quantized, designs_api.design_code(design_id)

@bp.route('/create-design/<design_type_name>')
def create_pro_design_form(design_type_name):
	try:
		cls = designs_encode.Design(design_type_name)
	except KeyError:
		return redirect('/create-design')

	return render_template('create_design_form.html', cls=cls)

@bp.route('/image/<image_id>')
@utils.token_exempt
def image(image_id):
	image_id = int(api.InvalidImageIdError.validate(image_id))
	data = designs_db.image(image_id)
	image_info = data['image']
	designs = data['designs']
	cls = designs_encode.Design(image_info['type_code'])
	cls_kwargs = dict(author_name=image_info['author_name'], design_name=image_info['image_name'])
	if image_info['pro']:
		layers = designs_db.gather_layers(cls, image_info['layers'])

		# pylint: disable=not-callable
		design = cls(layers=layers, **cls_kwargs)

		layers = [
			(
				name.capitalize().replace('-', ' '),
				utils.image_to_base64_url(utils.xbrz_scale_wand_in_subprocess(image, 6))
			)
			for name, image
			in design.layer_images.items()
		]
	else:
		img = wand.image.Image(width=image_info['width'], height=image_info['height'])
		img.import_pixels(data=image_info['layers'][0], channel_map='RGBA')
		if image_info['designs_required'] == 1:
			img = utils.xbrz_scale_wand_in_subprocess(img, 6)
		# pylint: disable=not-callable
		design = cls(**cls_kwargs, layers={'0': img})
		layers = [('0', utils.image_to_base64_url(img))]

	return render_template(
		'image.html',
		image=image_info, design=design, layers=layers, designs=designs,
		design_type=cls.display_name,
		preview=utils.image_to_base64_url(design.net_image()) if image_info['pro'] else None,
	)

@bp.route('/refresh-image/<image_id>')
@utils.token_exempt
# no rate limit because this endpoint has no effect if it doesn't need to run
def refresh_image(image_id):
	image_id = int(api.InvalidImageIdError.validate(image_id))
	results = stream_with_context(format_created_designs_gen(designs_db.refresh_image(image_id)))
	return utils.stream_template('created_image.html', image_id=image_id, results=results, verb='refreshed')

@bp.route('/image/<image_id>/delete', methods=['POST'])
def delete_image(image_id):
	image_id = int(api.InvalidImageIdError.validate(image_id))
	designs_db.delete_image(image_id)
	flash('Design deleted successfully.', 'success')
	return redirect('/')

@bp.errorhandler(ACNHError)
def handle_acnh_exception(ex):
	d = ex.to_dict()
	return render_template('error.html', message=d['error']), d['http_status']

@bp.errorhandler(HTTPException)
def handle_http_exception(ex):
	return render_template('error.html', message=ex.name, description=ex.get_description())

@bp.errorhandler(IncorrectAuthorizationError)
def handle_not_logged_in(ex):
	return redirect(url_for('.login', next=ex.path))
