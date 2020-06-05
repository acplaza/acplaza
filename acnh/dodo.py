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

import re
from http import HTTPStatus

from nintendo.nex.backend import BackEndClient
from nintendo.nex import matchmaking

from .common import authenticate_aauth, connect_backend, ACNHError, InvalidFormatError

class DodoCodeError(ACNHError):
	pass

class UnknownDodoCodeError(DodoCodeError):
	code = 11
	http_status = HTTPStatus.NOT_FOUND
	message = 'unknown dodo code'

class InvalidDodoCodeError(DodoCodeError, InvalidFormatError):
	code = 12
	message = 'invalid dodo code'
	regex = re.compile('[A-HJ-NP-Y0-9]{5}')

# _search_dodo_code is based on code provided by Yannik Marchand under the MIT License.
# Copyright (c) 2017 Yannik Marchand

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

def _search_dodo_code(backend: BackEndClient, dodo_code: str):
	mm = matchmaking.MatchmakeExtensionClient(backend.secure_client)

	param = matchmaking.MatchmakeSessionSearchCriteria()
	param.attribs = ['', '', '', '', '', '']
	param.game_mode = '2'
	param.min_players = '1'
	param.max_players = '1,8'
	param.matchmake_system = '1'
	param.vacant_only = False
	param.exclude_locked = True
	param.exclude_non_host_pid = True
	param.selection_method = 0
	param.vacant_participants = 1
	param.exclude_user_password = True
	param.exclude_system_password = True
	param.refer_gid = 0
	param.codeword = dodo_code

	sessions = mm.browse_matchmake_session_no_holder_no_result_range(param)
	if not sessions:
		raise UnknownDodoCodeError

	session = sessions[0]
	data = session.application_data
	return dict(
		active_players=session.player_count,
		name=data[12:32].decode('utf-16').rstrip('\0'),
		host=data[40:60].decode('utf-16').rstrip('\0'),
		start_time=
			dt.datetime.fromtimestamp(session.started_time.timestamp())
			.replace(tzinfo=dt.timezone.utc)
			.isoformat(),
	)

def search_dodo_code(dodo_code: str):
	InvalidDodoCodeError.validate(dodo_code)

	user_id, id_token = authenticate_aauth()
	backend = connect_backend(user_id, id_token)
	try:
		return _search_dodo_code(backend, dodo_code)
	finally:
		backend.close()
