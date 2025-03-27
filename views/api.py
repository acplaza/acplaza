import contextlib
import datetime as dt
import io
import json
import traceback
import urllib.parse

import quart.json
import wand.image
from quart import Blueprint, jsonify, current_app, request, stream_with_context
from quart_rate_limiter import rate_limit
from werkzeug.exceptions import HTTPException

from acnh import dodo
import acnh.designs.api as designs_api
import acnh.designs.render as designs_render
import acnh.designs.db as designs_db
import utils
import tarfile_stream
from acnh.errors import (
	ACNHError,
	InvalidDesignCodeError,
	MissingLayerError,
	InvalidScaleFactorError,
	CannotScaleThumbnailError,
	InvalidImageError,
	InvalidImageIdError,
	InvalidImageArgument,
	InvalidProArgument,
	InvalidAuthorIdError,
	TiledImageTooBigError,
	InvalidPaginationError,
	InvalidPaginationLimitError,
)
from acnh.designs.db import PageSpecifier, PageDirection
from acnh.designs.encode import BasicDesign, Design

def init_app(app):
	app.register_blueprint(bp)

bp = Blueprint('api', __name__, url_prefix='/api/v0')

@bp.route('/host-session/<dodo_code>')
@rate_limit(1, dt.timedelta(seconds=4))
async def host_session(dodo_code):
	return await dodo.search_dodo_code(dodo_code)

@bp.route('/design/<design_code>')
@rate_limit(5, dt.timedelta(seconds=1))
async def design(design_code):
	InvalidDesignCodeError.validate(design_code)
	return await designs_api.download_design(design_code)

def get_scale_factor():
	scale_factor = request.args.get('scale', '1')
	InvalidScaleFactorError.validate(scale_factor)
	return int(scale_factor)

async def maybe_scale(image):
	scale_factor = get_scale_factor()
	if scale_factor == 1:
		return image

	return await utils.xbrz_scale_wand_in_subprocess(image, scale_factor)

# TODO port to async

#@bp.route('/design/<design_code>.tar')
#@limiter.limit('2 per 10 seconds')
#def design_archive(design_code):
#	InvalidDesignCodeError.validate(design_code)
#	render_internal = 'internal_layers' in request.args
#	get_scale_factor()  # do the validation now since apparently it doesn't work in the generator
#	data = designs_api.download_design(design_code)
#	meta, body = data['mMeta'], data['mData']
#	# pylint: disable=unused-variable
#	type_code = meta['mMtUse']
#	design_name = meta['mMtDNm']  # hungarian notation + camel case + abbreviations DO NOT mix well
#
#	def gen():
#		# pylint: disable=no-member  # pylint are you drunk?
#		if type_code == BasicDesign.type_code or render_internal:
#			layers = designs_render.render_layers(body)
#		else:
#			layers = Design.from_data(data).layer_images.items()
#
#		yield from make_tar(design_name, data['updated_at'], layers)
#
#	encoded_filename = urllib.parse.quote(design_name + '.tar')
#	return current_app.response_class(
#		stream_with_context(gen()),
#		mimetype='application/x-tar',
#		headers={'Content-Disposition': f"attachment; filename*=utf-8''{encoded_filename}"},
#	)

#def make_tar(design_name, updated_at, layers):
#	tar = tarfile_stream.open(mode='w|')
#	yield from tar.header()
#
#	for name, image in layers:
#		tarinfo = tarfile_stream.TarInfo(f'{design_name}/{name}.png')
#		tarinfo.mtime = updated_at
#
#		image = maybe_scale(image)
#		out = io.BytesIO()
#		with image.convert('png') as c:
#			c.save(file=out)
#		tarinfo.size = out.tell()
#		out.seek(0)
#
#		yield from tar.addfile(tarinfo, out)
#
#	yield from tar.footer()

# no rate limit as we need to render the thumbnails for all of an author's designs quickly
@bp.route('/design/<design_code>/<layer>.png')
async def design_layer(design_code, layer):
	InvalidDesignCodeError.validate(design_code)
	data = await designs_api.download_design(design_code)
	meta, body = data['mMeta'], data['mData']
	design_name = meta['mMtDNm']

	if layer == 'thumbnail':
		if request.args.get('scale', '1') != '1':
			raise CannotScaleThumbnailError
		rendered = Design.from_data(data).net_image()
	else:
		try:
			int(layer)
		except ValueError:
			rendered = designs_render.render_layer_name(data, layer)
		else:
			rendered = designs_render.render_layer(body, layer)

	rendered = await maybe_scale(rendered)
	out = rendered.make_blob('png')

	encoded_filename = urllib.parse.quote(f'{design_name}-{layer}.png')
	return current_app.response_class(out, mimetype='image/png', headers={
		'Content-Length': len(out),
		'Content-Disposition': f"inline; filename*=utf-8''{encoded_filename}"
	})

@bp.route('/designs/<author_id>')
@rate_limit(5, dt.timedelta(seconds=1))
async def list_designs(author_id):
	author_id = int(InvalidAuthorIdError.validate(author_id).replace('-', ''))
	pro = request.args.get('pro', 'false')
	InvalidProArgument.validate(pro)

	page = await designs_api.list_designs(author_id, pro=pro)
	del page['offset'], page['count'], page['total']
	page['designs'] = page.pop('headers')
	page['creator_name'] = page['designs'][0]['design_player_name']
	page['author_id'] = page['designs'][0]['design_player_id']

	for d in page['designs']:
		d['design_code'] = designs_api.design_code(d['id'])
		del d['id']
		del d['design_player_name'], d['design_player_id'], d['digest']
		d['created_at'] = dt.datetime.utcfromtimestamp(d['created_at'])
		# designs cannot be updated, so why is this even here??
		del d['updated_at']

	return page

@bp.route('/images', methods=['POST'])
@rate_limit(1, dt.timedelta(seconds=15))
async def create_image():
	gen = stream_with_context(format_created_design_results)(create_image_gen())
	# Note: this is currently the only method (other than the rendering methods) which does *not* return JSON.
	# This is due to its iterative nature. I considered using JSON anyway, but very few libraries
	# support iterative JSON decoding, and we don't need anything other than an array anyway.
	return current_app.response_class(gen, mimetype='text/plain')

async def create_image_gen():
	reqvals = await request.values
	try:
		image_name = reqvals['image_name']
	except KeyError:
		raise InvalidImageArgument('image_name')

	author_name = reqvals.get('author_name') or 'Anonymous'  # we are legion

	design_type_name = reqvals.get('design_type', 'basic-design')
	try:
		if design_type_name == 'basic-design':
			async for x in create_basic_image(image_name, author_name):
				yield x
		else:
			async for x in create_pro_image(image_name, author_name, design_type_name):
				yield x
	except ACNHError as ex:
		yield ex.to_dict()

async def create_pro_image(image_name, author_name, design_type_name):
	try:
		layers = {
			filename: wand.image.Image(blob=file.read()).convert('PNG')
			for filename, file
			in (await request.files).items()
		}
	except wand.image.WandException:
		print('In:', request.path)
		traceback.print_exc()
		raise InvalidImageError

	design = Design(
		design_type_name,
		island_name=designs_db.island_name(),
		author_name=author_name,
		design_name=image_name,
		layers=layers,
	)

	with contextlib.ExitStack() as stack:
		for img in layers.values():
			stack.enter_context(img)
		for x in designs_db.create_image(design):
			yield x

async def create_basic_image(image_name, author_name):
	width = height = None

	reqvals = await request.values

	def get_int_value(name):
		v = reqvals.get(name)
		if not v:
			return None
		try:
			return int(v)
		except ValueError:
			raise InvalidImageArgument(name)

	try:
		width, height = map(int, reqvals['resize'].split('x'))
	except KeyError:
		width, height = map(get_int_value, ('resize-width', 'resize-height'))
	except ValueError:
		raise InvalidImageArgument('resize')

	scale = 'scale' in reqvals or reqvals.get('mode') == 'scale'

	try:
		img = wand.image.Image(blob=(await request.files)['0'].read()).convert('PNG')
	except wand.image.WandException as exc:
		print('In', request.path)
		traceback.print_exc()
		raise InvalidImageError
	except KeyError:
		# pylint: disable=no-member  # external_layers is defined dynamically
		raise MissingLayerError(BasicDesign.external_layers[0])

	if width is not None and not scale:
		img.transform(resize=f'{width}x{height}')
	# do this again now because custom exception handlers don't run for generators ¯\_(ツ)_/¯
	TiledImageTooBigError.validate(img)

	design = BasicDesign(
		island_name=designs_db.island_name(),
		author_name=author_name,
		design_name=image_name,
		layers={'0': img},
	)

	with img:
		async for x in designs_db.create_image(design, scale=scale):
			yield x

async def format_created_design_results(gen, *, header=True):
	def maybe_error(row):
		if isinstance(row, dict):
			return 'error: ' + quart.json.dumps(row)
		return None

	if header:
		# pylint: disable=stop-iteration-return  # this will never raise StopIteration
		row = await anext(gen)
		yield maybe_error(row) or str(row) + '\n'

	async for row in gen:
		err = maybe_error(row)
		if err:
			yield err
			return

		was_quantized, design_id = row
		yield f'{int(was_quantized)},{designs_api.design_code(design_id)}\n'

@bp.route('/images')
async def images():
	page = parse_keyset_params()
	rv = designs_db.images_keyset(page)
	async for i, image_info in utils.aenumerate(rv):
		rv[i] = image_info = dict(rv[i])
		# images are meant to be anonymous, with the author identified solely by their chosen name
		del image_info['author_id']
		image_info['design_type'] = Design(image_info.pop('type_code')).name
	return jsonify(rv)

def parse_keyset_params():
	# before='' means last
	# after='' means first
	before = request.args.get('before')
	after = request.args.get('after')
	limit = request.args.get('limit')
	if limit is not None:
		limit = int(InvalidPaginationLimitError.validate(limit))

	if before is None and after is None:
		# default to first page
		return PageSpecifier.first()

	if before is not None and after is not None:
		raise TwoPaginationReferencesPassedError

	if not before and not after:
		reference = None
	else:
		reference = int(InvalidImageIdError.validate(before or after))

	if before is not None:
		direction = PageDirection.before
	elif after is not None:
		direction = PageDirection.after

	return PageSpecifier(direction, reference, limit)

@bp.route('/image/<image_id>')
async def image(image_id):
	rv = await designs_db.image(int(InvalidImageIdError.validate(image_id)))
	# images are meant to be anonymous, with the author identified solely by their chosen name
	del rv['image']['author_id']
	rv['image']['design_type'] = Design(rv['image'].pop('type_code')).name
	return rv

# TODO async
#@bp.route('/image/<image_id>.tar')
@rate_limit(2, dt.timedelta(seconds=10))
async def image_archive(image_id):
	image_id = int(InvalidImageIdError.validate(image_id))
	image_info = (await designs_db.image(image_id))['image']
	render_internal = 'internal_layers' in request.args
	layers = {}
	cls = Design(image_info['type_code'])
	for layer, image_blob in zip(cls.external_layers, image_info['layers']):
		if image_info['pro']:
			layers[layer.name] = img = layer.as_wand()
		else:
			layers[layer.name] = img = wand.image.Image(width=image_info['width'], height=image_info['height'])

		img.import_pixels(channel_map='RGBA', data=image_blob)

	# pylint: disable=not-callable
	design = cls(layers=layers)
	if render_internal:
		requested_layers = enumerate(design.internalize())
	else:
		requested_layers = layers.items()

	gen = make_tar(image_info['image_name'], image_info['created_at'].timestamp(), requested_layers)
	encoded_filename = urllib.parse.quote(image_info['image_name'] + '.tar')
	return current_app.response_class(
		stream_with_context(gen),
		mimetype='application/x-tar',
		headers={
			'Content-Disposition': f"attachment; filename*=utf-8''{encoded_filename}",
		},
	)

@bp.route('/image/<image_id>/refresh', methods=['POST'])
async def refresh_image(image_id):
	gen = stream_with_context(format_created_design_results(_refresh_image(image_id), header=False))
	return current_app.response_class(gen, mimetype='text/plain')

async def _refresh_image(image_id):
	return await designs_db.refresh_image(int(InvalidImageIdError.validate(image_id)))

@bp.route('/image/<image_id>', methods=['DELETE'])
async def delete_image(image_id):
	image_id = int(InvalidImageIdError.validate(image_id))
	await designs_db.delete_image(image_id)
	return jsonify('OK')

@bp.errorhandler(HTTPException)
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
