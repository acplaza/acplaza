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

import datetime
import json
from http import HTTPStatus

from flask import Flask, jsonify, current_app

import acnh.dodo
import acnh.designs
import acnh.design_render
import utils
import tarfile_stream

app = Flask(__name__)
utils.init_app(app)

@app.route('/host-session/<dodo_code>')
def host_session(dodo_code):
	return acnh.dodo.search_dodo_code(dodo_code)

@app.route('/design/<design_code>')
def design(design_code):
	return acnh.designs.download_design(design_code)

@app.route('/design/<design_code>.tar')
def design_archive(design_code):
	data = acnh.designs.download_design(design_code)
	meta, body = data['mMeta'], data['mData']

	def gen():
		tar = tarfile_stream.open(mode='w|')
		yield from tar.header()
		for i, image in acnh.design_render.render_layers(body):
			tarinfo = tarfile_stream.TarInfo(f'{i}.png')
			tarinfo.mtime = datetime.datetime.utcnow().timestamp()
			tarinfo.size = len(image.getbuffer())
			yield from tar.addfile(tarinfo, image)
		yield from tar.footer()

	return current_app.response_class(gen(), mimetype='application/x-tar')

@app.route('/design/<design_code>/<int:layer>.png')
def design_layer(design_code, layer):
	data = acnh.designs.download_design(design_code)
	meta, body = data['mMeta'], data['mData']
	return current_app.response_class(acnh.design_render.render_layer(body, layer), mimetype='image/png')

with open('openapi.json') as f:
	open_api_spec = json.load(f)

@app.route('/')
def api_spec():
	return open_api_spec

if __name__ == '__main__':
	app.run(use_reloader=True)
