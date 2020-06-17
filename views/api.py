import contextlib
import datetime as dt
import io
import json
import random
import re
import urllib.parse
from functools import partial
from http import HTTPStatus

import xbrz
import wand.image
from flask import Blueprint, jsonify, current_app, request, stream_with_context, url_for, abort, session
from werkzeug.exceptions import HTTPException

import acnh.common as common
import acnh.dodo as dodo
import acnh.designs.api as designs_api
import acnh.designs.render as designs_render
import acnh.designs.db as designs_db
import utils
import tarfile_stream
from acnh.common import InvalidFormatError
from acnh.designs.api import DesignError, InvalidDesignCodeError
from acnh.designs.db import ImageError
from acnh.designs.encode import BasicDesign, Design, MissingLayerError, InvalidLayerNameError
from utils import limiter

def init_app(app):
	app.register_blueprint(bp)
	bp.errorhandler(HTTPException)(handle_exception)

bp = Blueprint('api', __name__, url_prefix='/api/v0')

class InvalidScaleFactorError(InvalidFormatError):
	message = 'invalid scale factor'
	code = 23
	regex = re.compile('[123456]')

class CannotScaleThumbnailError:
	message = 'cannot scale thumbnails'
	code = 29
	http_status = HTTPStatus.BAD_REQUEST

@bp.route('/host-session/<dodo_code>')
@limiter.limit('1 per 4 seconds')
def host_session(dodo_code):
	return dodo.search_dodo_code(dodo_code)

@bp.route('/design/<design_code>')
@limiter.limit('5 per second')
def design(design_code):
	InvalidDesignCodeError.validate(design_code)
	return designs_api.download_design(design_code)

def get_scale_factor():
	scale_factor = request.args.get('scale', '1')
	InvalidScaleFactorError.validate(scale_factor)
	return int(scale_factor)

def maybe_scale(image):
	scale_factor = get_scale_factor()
	if scale_factor == 1:
		return image

	return utils.xbrz_scale_wand_in_subprocess(image, scale_factor)

@bp.route('/design/<design_code>.tar')
@limiter.limit('2 per 10 seconds')
def design_archive(design_code):
	InvalidDesignCodeError.validate(design_code)
	render_internal = 'internal_layers' in request.args
	get_scale_factor()  # do the validation now since apparently it doesn't work in the generator
	data = designs_api.download_design(design_code)
	meta, body = data['mMeta'], data['mData']
	type_code = meta['mMtUse']
	design_name = meta['mMtDNm']  # hungarian notation + camel case + abbreviations DO NOT mix well

	def gen():
		tar = tarfile_stream.open(mode='w|')
		yield from tar.header()

		if type_code == BasicDesign.type_code or render_internal:
			layers = designs_render.render_layers(body)
		else:
			layers = Design.from_data(data).layer_images.items()

		for name, image in layers:
			tarinfo = tarfile_stream.TarInfo(f'{design_name}/{name}.png')
			tarinfo.mtime = data['updated_at']

			image = maybe_scale(image)
			out = io.BytesIO()
			with image.convert('png') as c:
				c.save(file=out)
			tarinfo.size = out.tell()
			out.seek(0)

			yield from tar.addfile(tarinfo, out)

		yield from tar.footer()

	encoded_filename = urllib.parse.quote(design_name + '.tar')
	return current_app.response_class(
		stream_with_context(gen()),
		mimetype='application/x-tar',
		headers={'Content-Disposition': f"attachment; filename*=utf-8''{encoded_filename}"},
	)

# no rate limit as we need to render the thumbnails for all of an author's designs quickly
@bp.route('/design/<design_code>/<layer>.png')
def design_layer(design_code, layer):
	InvalidDesignCodeError.validate(design_code)
	data = designs_api.download_design(design_code)
	meta, body = data['mMeta'], data['mData']
	type_code = meta['mMtUse']
	design_name = meta['mMtDNm']

	if layer == 'thumbnail':
		if request.args.get('scale', '1') != '1':
			raise CannotScaleThumbnailError
		rendered = Design.from_data(data).net_image()
	else:
		try:
			layer_i = int(layer)
		except ValueError:
			rendered = designs_render.render_layer_name(data, layer)
		else:
			rendered = designs_render.render_layer(body, layer_i)

	rendered = maybe_scale(rendered)
	out = rendered.make_blob('png')

	encoded_filename = urllib.parse.quote(f'{design_name}-{layer}.png')
	return current_app.response_class(out, mimetype='image/png', headers={
		'Content-Length': len(out),
		'Content-Disposition': f"inline; filename*=utf-8''{encoded_filename}"
	})

class InvalidProArgument(DesignError, InvalidFormatError):
	message = 'invalid value for pro argument'
	code = 25
	regex = re.compile('[01]|(?:false|true)|[ft]', re.IGNORECASE)

@bp.route('/designs/<author_id>')
@limiter.limit('5 per 1 seconds')
def list_designs(author_id):
	author_id = int(designs_api.InvalidAuthorIdError.validate(author_id).replace('-', ''))
	pro = request.args.get('pro', 'false')
	InvalidProArgument.validate(pro)

	page = designs_api.list_designs(author_id, offset=offset, limit=limit, pro=pro)
	page['creator_name'] = page['headers'][0]['design_player_name']
	page['author_id'] = page['headers'][0]['design_player_id']

	for hdr in page['headers']:
		hdr['design_code'] = designs_api.design_code(hdr['id'])
		del hdr['meta'], hdr['body'], hdr['design_player_name'], hdr['design_player_id'], hdr['digest']
		for dt_key in 'created_at', 'updated_at':
			hdr[dt_key] = dt.datetime.utcfromtimestamp(hdr[dt_key])

	return page

class InvalidImageArgument(ImageError):
	code = 36
	message = 'missing or invalid required image argument {.argument_name}'
	http_status = HTTPStatus.BAD_REQUEST

	def __init__(self, argument_name):
		self.argument_name = argument_name

	def to_dict(self):
		d = super().to_dict()
		d['argument_name'] = self.argument_name
		d['error'] = d['error'].format(self)
		return d

# TODO add which layer failed
class InvalidImageError(ImageError):
	code = 39
	message = 'One or more layers submitted represented an invalid image.'
	status = HTTPStatus.BAD_REQUEST

class InvalidImageIdError(ImageError, InvalidFormatError):
	code = 41  # XXX rip my nice "x/10 = category" system
	message = 'Invalid image ID.'
	regex = re.compile('[0-9]+')

ISLAND_NAMES = [
	'The Cloud',
	'Black Lives Matter',
	'ACAB',
]

island_name = partial(random.choice, ISLAND_NAMES)

@bp.route('/images', methods=['POST'])
@limiter.limit('1 per 15s')
def create_image():
	gen = format_created_design_results(_create_image())
	# Note: this is currently the only method (other than the rendering methods) which does *not* return JSON.
	# This is due to its iterative nature. I considered using JSON anyway, but very few libraries
	# support iterative JSON decoding, and we don't need anything other than an array anyway.
	return current_app.response_class(stream_with_context(gen), mimetype='text/plain')

def _create_image():
	try:
		image_name = request.values['image_name']
	except KeyError:
		raise InvalidImageArgument('image_name')

	author_name = request.values.get('author_name', 'Anonymous')  # we are legion

	try:
		design_type_name = request.values['design_type']
	except KeyError:
		return create_basic_image(image_name, author_name)
	else:
		if design_type_name == 'basic-design':
			return create_basic_image(image_name, author_name)
		return create_pro_image(image_name, author_name, design_type_name)

def create_pro_image(image_name, author_name, design_type_name):
	try:
		layers = {filename: wand.image.Image(file=file) for filename, file in request.files.items()}
	except wand.image.WandException:
		raise InvalidImageError

	design = Design(
		design_type_name,
		island_name=island_name(),
		author_name=author_name,
		design_name=image_name,
		layers=layers,
	)

	def gen():
		with contextlib.ExitStack() as stack:
			for img in layers.values():
				stack.enter_context(img)
			yield from designs_db.create_image(design)

	return gen()

def create_basic_image(image_name, author_name):
	width = height = None

	def get_int_value(name):
		v = request.values.get(name)
		if not v:
			return None
		try:
			return int(v)
		except ValueError:
			raise InvalidImageArgument(name)

	try:
		width, height = map(int, request.values['resize'].split('x'))
	except KeyError:
		width, height = map(get_int_value, ('resize-width', 'resize-height'))
	except ValueError:
		raise InvalidImageArgument('resize')
	else:
		if len(resize) != 2:
			raise InvalidImageArgument('resize')

	scale = 'scale' in request.values or request.values.get('mode') == 'scale'

	try:
		img = wand.image.Image(file=request.files['0'])
	except wand.image.WandException:
		raise InvalidImageError
	except KeyError:
		raise MissingLayerError(BasicDesign.external_layers[0])

	if width is not None and not scale:
		img.transform(resize=f'{width}x{height}')
	# do this again now because custom exception handlers don't run for generators ¯\_(ツ)_/¯
	designs_db.TiledImageTooBigError.validate(img)

	design = BasicDesign(island_name=island_name(), author_name=author_name, design_name=image_name, layers={'0': img})

	def gen():
		with img:
			yield from designs_db.create_image(design, scale=scale)

	return gen()

def format_created_design_results(gen):
	image_id = next(gen)
	yield str(image_id) + '\n'
	for was_quantized, design_id in gen:
		yield f'{int(was_quantized)},{designs_api.design_code(design_id)}\n'

@bp.route('/image/<image_id>')
def image(image_id):
	rv = designs_db.image(int(InvalidImageIdError.validate(image_id)))
	designs = rv['designs']
	for i, design in enumerate(designs):
		d = designs[i] = dict(design)
		d['design_code'] = designs_api.design_code(design['design_id'])

	return rv

class InvalidImageDeletionToken(ImageError, InvalidFormatError):
	code = 42
	message = 'invalid image deletion token'
	regex = re.compile('[a-zA-Z0-9]+')

@bp.route('/image/<image_id>', methods=['DELETE'])
def delete_image(image_id):
	token = bytes.fromhex(InvalidImageDeletionToken.validate(request.args.get('token', '')))
	image_id = int(InvalidImageIdError.validate(image_id))
	designs_db.delete_image(image_id, token)
	return jsonify('OK')

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
