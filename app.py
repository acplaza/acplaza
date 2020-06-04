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

import json
from http import HTTPStatus

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import acnh.dodo
import acnh.designs
import utils

app = Flask(__name__)
app.json_encoder = utils.UnicodeJSONEncoder

@app.route('/host-session/<dodo_code>')
def host_session(dodo_code):
	try:
		return acnh.dodo.search_dodo_code(dodo_code)
	except acnh.dodo.UnknownDodoCodeError as ex:
		return ex.to_dict(), HTTPStatus.NOT_FOUND
	except acnh.dodo.InvalidDodoCodeError as ex:
		return ex.to_dict(), HTTPStatus.BAD_REQUEST

@app.route('/design/<design_code>')
def design(design_code):
	try:
		return acnh.designs.download_design(design_code)
	except acnh.designs.UnknownDesignCodeError as ex:
		return ex.to_dict(), HTTPStatus.NOT_FOUND
	except acnh.designs.InvalidDesignCodeError as ex:
		return ex.to_dict(), HTTPStatus.BAD_REQUEST

with open('openapi.json') as f:
	open_api_spec = json.load(f)

@app.route('/')
def api_spec():
	return open_api_spec

@app.errorhandler(HTTPException)
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

if __name__ == '__main__':
	app.run(use_reloader=True)
