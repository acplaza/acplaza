# © 2020 io mintz <io@mintz.cc>

import datetime as dt
import re
from http import HTTPStatus

from nintendo.nex import matchmaking

from .errors import UnknownDodoCodeError, InvalidDodoCodeError

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

def search_dodo_code(dodo_code: str):
	InvalidDodoCodeError.validate(dodo_code)

	mm = matchmaking.MatchmakeExtensionClient(backend().secure_client)

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
		start_time=dt.datetime.fromtimestamp(session.started_time.timestamp()),
	)
