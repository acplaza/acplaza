# © 2020 io mintz <io@mintz.cc>

import contextlib
import random
import secrets
import time
from http import HTTPStatus
from functools import partial
from typing import Dict, Iterable, Tuple

import wand.image
from flask import session

from ..common import ACNHError
from . import api, encode
from .format import SIZE, WIDTH, HEIGHT, BYTES_PER_PIXEL
from utils import config, pg, queries

class ImageError(ACNHError):
	pass

class UnknownImageIdError(ImageError):
	code = 31
	message = 'unknown image ID'
	http_status = HTTPStatus.NOT_FOUND

class DeletionDeniedError(ImageError):
	code = 32
	message = 'you do not own this image'
	http_status = HTTPStatus.UNAUTHORIZED

def garbage_collect_designs(needed_slots: int, *, pro: bool):
	"""Free at least needed_slots. Pass pro depending on whether Pro slots are needed."""
	design_ids = pg().fetchvals(queries.stale_designs(), pro, needed_slots)
	for design_id in design_ids:
		try:
			api.delete_design(design_id)
		except api.UnknownDesignCodeError:
			print(
				'Design ID:',
				design_id,
				'code:',
				api.design_code(design_id),
				'found in the database but not in the slots! Ignoring.',
			)
	pg().execute(queries.delete_designs(), design_ids)

def delete_image(image_id):
	image_author_id = pg().fetchval(queries.image_author_id(), image_id)
	valid = image_author_id == session['user_id']
	if image_author_id is None:
		raise UnknownImageIdError
	elif not valid:
		raise DeletionDeniedError

	with pg().transaction(isolation='serializable'):
		design_ids = pg().fetchvals(queries.delete_image_designs(), image_id)
		pg().execute(queries.delete_image(), image_id)

	for design_id in design_ids:
		api.delete_design(design_id)

class InvalidImageError(ImageError):
	http_status = HTTPStatus.BAD_REQUEST

class SingleLayerRequired(InvalidImageError):
	code = 33
	message = (
		'A single layer was required, but more than one was passed. '
		'If tiling was requested, do not pass multiple layers.'
	)

class InvalidLayerSizeError(InvalidImageError):
	code = 34
	message = 'One or more layers was not {0.width}×{0.height}.'

	def __init__(self, width, height):
		super().__init__()
		self.width = width
		self.height = height

	def to_dict(self):
		d = super().to_dict()
		d['expected_width'] = self.width
		d['expected_height'] = self.height
		d['expected_byte_length'] = self.width * self.height * BYTES_PER_PIXEL
		d['message'] = self.message.format(self)
		return d

MAX_DESIGN_TILES = 16

class TiledImageTooBigError(InvalidImageError):
	code = 35
	message = f'The uploaded image would exceed {MAX_DESIGN_TILES} tiles.'
	status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE

	@classmethod
	def validate(cls, img):
		if img.width // WIDTH * img.height // HEIGHT > MAX_DESIGN_TILES:
			raise cls

def create_image(design, **kwargs):
	return (create_pro_design if design.pro else create_basic_design)(design, **kwargs)

def create_pro_design(design):
	"""Upload a pro design. Returns an iterable for consistency with create_basic_design."""
	deletion_token = secrets.token_bytes()
	image_id = pg().fetchval(
		queries.create_image(),

		session['user_id'],
		design.author_name,
		design.design_name,
		None,
		None,
		design.type_code,
		[bytearray(image.export_pixels()) for image in design.layer_images.values()],
		deletion_token,
	)
	garbage_collect_designs(1, pro=True)
	was_quantized, encoded = encode.encode(design)
	design_id = api.create_design(encoded)
	create_design(image_id=image_id, design_id=design_id, position=0, pro=True)
	yield image_id
	yield was_quantized, design_id

def create_basic_design(design, *, scale: bool):
	"""Upload a basic design. Scale controls whether to tile or scale the image. Returns an iterable of design IDs."""
	image = design.layer_images['0']
	if image.size > SIZE and not scale:
		TiledImageTooBigError.validate(image)
		# backwards so that the first image shows up first in game
		images = list(encode.tile(image.clone()))[::-1]
	else:  # scale if necessary
		images = [image.clone()]

	deletion_token = secrets.token_bytes()
	# XXX is it a Design class or an Image class. It's both! Is that OK?
	image_id = pg().fetchval(
		queries.create_image(),

		session['user_id'],
		design.author_name,
		design.design_name,
		image.width,
		image.height,
		design.type_code,
		[bytearray(image.export_pixels())],
		deletion_token,
	)
	yield image_id
	for i, image in zip(reversed(range(1, len(images) + 1)), reversed(images)):
		design_name = f'{design.design_name} {i}' if len(images) > 1 else design.design_name
		sub_design = encode.BasicDesign(
			design_name=design_name,
			island_name=design.island_name,
			author_name=design.author_name,
			layers={'0': image},
		)
		# we do this on each loop in case someone uploaded a few more designs in between iterations
		garbage_collect_designs(len(images) - (i - 1), pro=False)
		# designs get out of order if we post them too fast
		time.sleep(0.5)
		was_quantized, encoded = encode.encode(sub_design)
		design_id = api.create_design(encoded)
		create_design(image_id=image_id, design_id=design_id, position=i, pro=False)
		yield was_quantized, design_id

def create_design(*, image_id, design_id, position, pro):
	pg().execute(queries.create_design(), image_id, design_id, position, pro)

def image(image_id):
	rows = pg().fetch(queries.image_designs(), image_id)
	if not rows:
		raise UnknownImageIdError
	image = dict(rows[0])
	# these are design fields not image fields
	del image['design_id'], image['position']
	designs = []
	for row in rows:
		design = {}
		designs.append(design)
		design['design_id'] = row['design_id']
		design['design_code'] = api.design_code(row['design_id'])
		design['position'] = row['position']
	return {'image': image, 'designs': designs}
