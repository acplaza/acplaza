#!/usr/bin/env python3

from flask import Blueprint, render_template, session, request

import utils

def init_app(app):
	app.register_blueprint(bp)

bp = Blueprint('frontend', __name__)

@bp.route('/login')
@utils.token_exempt
def login_form():
	return render_template('login.html')

@bp.route('/login', methods=['POST'])
@utils.token_exempt
def login():
	try:
		token = request.form['token']
	except KeyError:
		# we don't need to have a fancy error class for this one because the user is intentionally fucking
		# with the form
		abort(HTTPStatus.UNAUTHORIZED)

	if utils.validate_token(token):
		session['authed'] = 1

	return 'OK'
