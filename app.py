#!/usr/bin/env python3

# © 2020 io mintz <io@mintz.cc>

# ACNH API is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# ACNH API is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with ACNH API. If not, see <https://www.gnu.org/licenses/>.

import datetime as dt
import io
import json
from http import HTTPStatus

from flask import Flask, jsonify, current_app, request, stream_with_context, url_for

import acnh.dodo
import acnh.designs
import acnh.design_render
import utils
import re
import tarfile_stream
import xbrz
from acnh.common import ACNHError, InvalidFormatError
from acnh.designs import DesignError

app = Flask(__name__)
utils.init_app(app)

class InvalidScaleFactorError(InvalidFormatError):
	message = 'invalid scale factor'
	code = 23
	regex = re.compile('[123456]')

@app.route('/host-session/<dodo_code>')
def host_session(dodo_code):
	return acnh.dodo.search_dodo_code(dodo_code)

@app.route('/design/<design_code>')
def design(design_code):
	InvalidDesignCodeError.validate(design_code)
	return acnh.designs.download_design(acnh.designs.design_id(design_code))

def get_scale_factor():
	scale_factor = request.args.get('scale', '1')
	InvalidScaleFactorError.validate(scale_factor)
	return int(scale_factor)

def maybe_scale(image):
	scale_factor = get_scale_factor()
	if scale_factor == 1:
		return image

	return xbrz.scale_pil(image, scale_factor)

@app.route('/design/<design_code>.tar')
def design_archive(design_code):
	InvalidDesignCodeError.validate(design_code)
	get_scale_factor()  # do the validation now since apparently it doesn't work in the generator
	data = acnh.designs.download_design(design_code)
	meta, body = data['mMeta'], data['mData']
	design_name = meta['mMtDNm']  # hungarian notation + camel case + abbreviations DO NOT mix well

	def gen():
		tar = tarfile_stream.open(mode='w|')
		yield from tar.header()

		for i, image in acnh.design_render.render_layers(body):
			tarinfo = tarfile_stream.TarInfo(f'{design_name}/{i}.png')
			tarinfo.mtime = dt.datetime.utcnow().timestamp()

			image = maybe_scale(image)
			out = io.BytesIO()
			image.save(out, format='PNG')
			tarinfo.size = out.tell()
			out.seek(0)

			yield from tar.addfile(tarinfo, out)

		yield from tar.footer()

	return current_app.response_class(
		stream_with_context(gen()),
		mimetype='application/x-tar',
		headers={'Content-Disposition': f"attachment; filename*=utf-8''{design_name}.tar"},
	)

@app.route('/design/<design_code>/<int:layer>.png')
def design_layer(design_code, layer):
	InvalidDesignCodeError.validate(design_code)
	data = acnh.designs.download_design(acnh.designs.design_id(design_code))
	meta, body = data['mMeta'], data['mData']
	design_name = meta['mMtDNm']

	rendered = acnh.design_render.render_layer(body, layer)
	rendered = maybe_scale(rendered)
	out = io.BytesIO()
	rendered.save(out, format='PNG')
	length = out.tell()
	out.seek(0)
	return current_app.response_class(out, mimetype='image/png', headers={
		'Content-Length': length,
		'Content-Disposition': f"inline; filename*=utf-8''{design_name}-{layer}.png"
	})

class InvalidProArgument(DesignError, InvalidFormatError):
	message = 'invalid value for pro argument'
	code = 25
	regex = re.compile('[01]|(?:false|true)|[ft]', re.IGNORECASE)

@app.route('/designs/<creator_id>')
def list_designs(creator_id):
	InvalidCreatorIdError.validate(creator_id)
	creator_id = int(creator_id.replace('-', ''))
	pro = request.args.get('pro', 'false')
	InvalidProArgument.validate(pro)

	page = acnh.designs.list_designs(creator_id, offset=offset, limit=limit, pro=pro)
	page['creator_name'] = page['headers'][0]['design_player_name']
	page['creator_id'] = page['headers'][0]['design_player_id']

	for hdr in page['headers']:
		hdr['design_code'] = acnh.designs.design_code(hdr['id'])
		del hdr['meta'], hdr['body'], hdr['design_player_name'], hdr['design_player_id'], hdr['digest']
		for dt_key in 'created_at', 'updated_at':
			hdr[dt_key] = dt.datetime.utcfromtimestamp(hdr[dt_key])

	return page

if __name__ == '__main__':
	app.run(use_reloader=True)
