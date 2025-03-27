#!/usr/bin/env python3
# © 2020 io mintz <io@mintz.cc>

from glob import glob

from quart import Quart

import utils
import acnh.common
import views.api
import views.frontend

app = Quart(__name__)
utils.init_app(app)
acnh.common.init_app(app)
views.frontend.init_app(app)
views.api.init_app(app)

if __name__ == '__main__':
	app.run(use_reloader=True)
