#!/usr/bin/env python3

# © 2020 io mintz <io@mintz.cc>

import datetime as dt
import io
import json
import re
import urllib.parse
from http import HTTPStatus

import wand.image
from flask import Flask, jsonify, current_app, request, stream_with_context, url_for, abort
from flask_limiter import Limiter
from flask_limiter.util import get_ipaddr

import acnh.common as common
import acnh.dodo as dodo
import acnh.designs.api as designs_api
import acnh.designs.render as designs_render
import acnh.designs.db as designs_db
import utils
import tarfile_stream
import xbrz
from acnh.common import ACNHError, InvalidFormatError
from acnh.designs.api import DesignError, InvalidDesignCodeError
from acnh.designs.db import ImageError

app = Flask(__name__)
utils.init_app(app)
common.init_app(app)
limiter = Limiter(app, key_func=get_ipaddr)

class InvalidScaleFactorError(InvalidFormatError):
	message = 'invalid scale factor'
	code = 23
	regex = re.compile('[123456]')

@app.route('/host-session/<dodo_code>')
@limiter.limit('1 per 4 seconds')
def host_session(dodo_code):
	return dodo.search_dodo_code(dodo_code)

@app.route('/design/<design_code>')
@limiter.limit('5 per second')
def design(design_code):
	InvalidDesignCodeError.validate(design_code)
	return designs_api.download_design(designs_api.design_id(design_code))

def get_scale_factor():
	scale_factor = request.args.get('scale', '1')
	InvalidScaleFactorError.validate(scale_factor)
	return int(scale_factor)

def maybe_scale(image):
	scale_factor = get_scale_factor()
	if scale_factor == 1:
		return image

	return utils.xbrz_scale_wand_in_subprocess(image, scale_factor)

@app.route('/design/<design_code>.tar')
@limiter.limit('2 per 10 seconds')
def design_archive(design_code):
	InvalidDesignCodeError.validate(design_code)
	get_scale_factor()  # do the validation now since apparently it doesn't work in the generator
	data = designs_api.download_design(designs_api.design_id(design_code))
	meta, body = data['mMeta'], data['mData']
	design_name = meta['mMtDNm']  # hungarian notation + camel case + abbreviations DO NOT mix well

	def gen():
		tar = tarfile_stream.open(mode='w|')
		yield from tar.header()

		for i, image in designs_render.render_layers(body):
			tarinfo = tarfile_stream.TarInfo(f'{design_name}/{i}.png')
			tarinfo.mtime = dt.datetime.utcnow().timestamp()

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

@app.route('/design/<design_code>/<int:layer>.png')
@limiter.limit('12 per 10 seconds')
def design_layer(design_code, layer):
	InvalidDesignCodeError.validate(design_code)
	data = designs_api.download_design(designs_api.design_id(design_code))
	meta, body = data['mMeta'], data['mData']
	design_name = meta['mMtDNm']

	rendered = designs_render.render_layer(body, layer)
	rendered = maybe_scale(rendered)
	out = io.BytesIO()
	with rendered.convert('png') as c:
		c.save(out)
	length = out.tell()
	out.seek(0)

	encoded_filename = urllib.parse.quote(f'{design_name}-{layer}.png')
	return current_app.response_class(out, mimetype='image/png', headers={
		'Content-Length': length,
		'Content-Disposition': f"inline; filename*=utf-8''{encoded_filename}"
	})

class InvalidProArgument(DesignError, InvalidFormatError):
	message = 'invalid value for pro argument'
	code = 25
	regex = re.compile('[01]|(?:false|true)|[ft]', re.IGNORECASE)

@app.route('/designs/<creator_id>')
@limiter.limit('5 per 1 seconds')
def list_designs(creator_id):
	creator_id = int(designs_api.InvalidCreatorIdError.validate(creator_id).replace('-', ''))
	pro = request.args.get('pro', 'false')
	InvalidProArgument.validate(pro)

	page = designs_api.list_designs(creator_id, offset=offset, limit=limit, pro=pro)
	page['creator_name'] = page['headers'][0]['design_player_name']
	page['creator_id'] = page['headers'][0]['design_player_id']

	for hdr in page['headers']:
		hdr['design_code'] = designs_api.design_code(hdr['id'])
		del hdr['meta'], hdr['body'], hdr['design_player_name'], hdr['design_player_id'], hdr['digest']
		for dt_key in 'created_at', 'updated_at':
			hdr[dt_key] = dt.datetime.utcfromtimestamp(hdr[dt_key])

	return page

# XXX maybe 10 error codes per category isn't enough, because I want to split this up in two,
# but then I wouldn't have room for InvalidImageError
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

class InvalidImageLayerNameError(ImageError, InvalidFormatError):
	code = 37
	message = 'Invalid image layer name format.'
	regex = re.compile('[0-9]')

class MissingImageLayersError(ImageError):
	code = 38
	message = (
		'Payload was missing one or more image layers. '
		'Make sure your layer names are continuous non-negative integers starting at 0.'
	)
	status = HTTPStatus.BAD_REQUEST

class InvalidImageError(ImageError):
	code = 39
	message = 'One or more layers submitted represented an invalid image.'
	status = HTTPStatus.BAD_REQUEST

class InvalidImageIdError(ImageError, InvalidFormatError):
	code = 41  # rip my nice x/10 = category system
	message = 'Invalid image ID.'
	regex = re.compile('[0-9]+')

@app.route('/images', methods=['POST'])
@limiter.limit('1 per 15s')
def create_image():
	try:
		name = request.args['image_name']
	except KeyError:
		raise InvalidImageArgument('image_name')

	try:
		resize = tuple(map(int, request.args['resize'].split('x')))
	except KeyError:
		resize = None
	except ValueError:
		raise InvalidImageArgument('resize')
	else:
		if len(resize) != 2:
			raise InvalidImageArgument('resize')

	author_name = request.args.get('author_name', 'Anonymous')  # we are legion
	scale = 'scale' in request.args
	if len(request.files) > 1:
		# just until we get pro designs goin'
		abort(HTTPStatus.BAD_REQUEST)
	if '0' not in request.files:
		abort(HTTPStatus.BAD_REQUEST)

	try:
		img = wand.image.Image(blob=request.files['0'].read())
	except wand.image.Exception:
		raise InvalidImageError

	if resize is not None:
		img.transform(resize=f'{resize[0]}x{resize[1]}')
	# do this again now because custom exception handlers don't run for generators ¯\_(ツ)_/¯
	designs_db.TiledImageTooBigError.validate(img)

	def gen():
		with img:
			for design_id in designs_db.create_image(
				author_name=author_name,
				image_name=name,
				image=img,
				scale=scale,
			):
				yield designs_api.design_code(design_id) + '\n'

	# Note: this is currently the only method (other than the rendering methods) which does *not* return JSON.
	# This is due to its iterative nature. I considered using JSON anyway, but very few libraries
	# support iterative JSON decoding, and we don't need anything other than an array of strings anyway.
	return current_app.response_class(stream_with_context(gen()), mimetype='text/plain')

@app.route('/image/<image_id>')
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

@app.route('/image/<image_id>', methods=['DELETE'])
def delete_image(image_id):
	token = bytes.fromhex(InvalidImageDeletionToken.validate(request.args.get('token', '')))
	image_id = int(InvalidImageIdError.validate(image_id))
	designs_db.delete_image(image_id, token)
	return jsonify('OK')

if __name__ == '__main__':
	app.run(use_reloader=True)
