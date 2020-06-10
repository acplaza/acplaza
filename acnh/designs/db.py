# © 2020 io mintz <io@mintz.cc>

import contextlib
import random
import secrets
import time
from http import HTTPStatus
from functools import partial
from typing import Iterable

import wand.image

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

class IncorrectImageDeletionTokenError(ImageError):
	code = 32
	message = 'incorrect image deletion token'
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

def delete_image(image_id, deletion_token):
	valid = pg().fetchval(queries.check_deletion_token(), image_id)
	if valid is None:
		raise UnknownImageIdError
	elif not valid:
		raise IncorrectDeletionTokenError

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

ISLAND_NAMES = [
	'The Cloud',
	'Black Lives Matter',
	'TRAHR',
	'ACAB',
]

island_name = partial(random.choice, ISLAND_NAMES)

def create_image(*, author_name, image_name, image: wand.image.Image, scale: bool) -> Iterable[int]:
	"""Upload a design. Scale controls whether to tile or scale the image. Returns an iterable of design IDs."""
	if image.size > SIZE and not scale:
		TiledImageTooBigError.validate(image)
		# backwards so that the first image shows up first in game
		designs = list(encode.tile(image.clone()))[::-1]
	else:  # scale if necessary
		designs = [image.clone()]

	deletion_token = secrets.token_bytes()
	image_id = pg().fetchval(
		queries.create_image(),
		author_name, image_name, image.width, image.height, [bytearray(image.export_pixels())], deletion_token,
	)
	island_name_ = island_name()
	for i, design in zip(reversed(range(1, len(designs) + 1)), designs):
		design_name = f'{image_name} {i}' if len(designs) > 1 else image_name
		# we do this on each loop in case someone uploaded a few more designs in between iterations
		garbage_collect_designs(len(designs) - (i - 1), pro=False)
		# designs get out of order if we post them too fast
		time.sleep(0.5)
		design_id = api.create_design(encode.encode(island_name_, design_name, design))
		create_design(image_id=image_id, design_id=design_id, position=i, pro=False)
		yield design_id

def create_design(*, image_id, design_id, position, pro):
	pg().execute(queries.create_design(), image_id, design_id, position, pro)

def image(image_id):
	image = pg().fetchrow(queries.image(), image_id)
	if image is None:
		raise UnknownImageIdError
	return {'image': image, 'designs': pg().fetch(queries.image_designs(), image_id)}
