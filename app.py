#!/usr/bin/env python3

# © 2020 io mintz <io@mintz.cc>

import datetime as dt
import io
import json
import urllib.parse
from http import HTTPStatus

from flask import Flask, jsonify, current_app, request, stream_with_context, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_ipaddr

import acnh.dodo
import acnh.designs.api
import acnh.designs.render
import utils
import re
import tarfile_stream
import xbrz
from acnh.common import ACNHError, InvalidFormatError
from acnh.designs.api import DesignError, InvalidDesignCodeError

app = Flask(__name__)
utils.init_app(app)
limiter = Limiter(app, key_func=get_ipaddr)

class InvalidScaleFactorError(InvalidFormatError):
	message = 'invalid scale factor'
	code = 23
	regex = re.compile('[123456]')

@app.route('/host-session/<dodo_code>')
@limiter.limit('1 per 4 seconds')
def host_session(dodo_code):
	return acnh.dodo.search_dodo_code(dodo_code)

@app.route('/design/<design_code>')
@limiter.limit('5 per second')
def design(design_code):
	InvalidDesignCodeError.validate(design_code)
	return acnh.designs.api.download_design(acnh.designs.api.design_id(design_code))

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
	data = acnh.designs.api.download_design(acnh.designs.api.design_id(design_code))
	meta, body = data['mMeta'], data['mData']
	design_name = meta['mMtDNm']  # hungarian notation + camel case + abbreviations DO NOT mix well

	def gen():
		tar = tarfile_stream.open(mode='w|')
		yield from tar.header()

		for i, image in acnh.designs.render.render_layers(body):
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
	data = acnh.designs.api.download_design(acnh.designs.api.design_id(design_code))
	meta, body = data['mMeta'], data['mData']
	design_name = meta['mMtDNm']

	rendered = acnh.designs.render.render_layer(body, layer)
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
	InvalidCreatorIdError.validate(creator_id)
	creator_id = int(creator_id.replace('-', ''))
	pro = request.args.get('pro', 'false')
	InvalidProArgument.validate(pro)

	page = acnh.designs.api.list_designs(creator_id, offset=offset, limit=limit, pro=pro)
	page['creator_name'] = page['headers'][0]['design_player_name']
	page['creator_id'] = page['headers'][0]['design_player_id']

	for hdr in page['headers']:
		hdr['design_code'] = acnh.designs.api.design_code(hdr['id'])
		del hdr['meta'], hdr['body'], hdr['design_player_name'], hdr['design_player_id'], hdr['digest']
		for dt_key in 'created_at', 'updated_at':
			hdr[dt_key] = dt.datetime.utcfromtimestamp(hdr[dt_key])

	return page

if __name__ == '__main__':
	app.run(use_reloader=True)
