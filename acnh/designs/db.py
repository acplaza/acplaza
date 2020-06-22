# © 2020 io mintz <io@mintz.cc>

import contextlib
import random
import time
from http import HTTPStatus
from functools import partial
from typing import Dict, Iterable, Tuple

import wand.image
from flask import session

from ..common import ACNHError
from . import api, encode
from .format import SIZE, WIDTH, HEIGHT, BYTES_PER_PIXEL, MAX_DESIGN_TILES
from utils import config, pg, queries
from ..errors import UnknownImageIdError, DeletionDeniedError, InvalidLayerSizeError, TiledImageTooBigError

ISLAND_NAMES = [
	'The Cloud',
	'Black Lives Matter',
	'ACAB',
]

island_name = partial(random.choice, ISLAND_NAMES)

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

def num_tiles(width, height):
	return width // WIDTH * height // HEIGHT

def create_image(design, **kwargs):
	return (create_pro_design if design.pro else create_basic_design)(design, **kwargs)

def create_pro_design(design):
	"""Upload a pro design. Returns an iterable for consistency with create_basic_design."""
	image_id = pg().fetchval(
		queries.create_image(),

		session['user_id'],
		design.author_name,
		design.design_name,
		None,  # width
		None,  # height
		None,  # mode
		design.type_code,
		[bytearray(image.export_pixels()) for image in design.layer_images.values()],
	)
	garbage_collect_designs(1, pro=True)
	was_quantized, encoded = encode.encode(design)
	design_id = api.create_design(encoded)
	create_design(image_id=image_id, design_id=design_id, position=1, pro=True)
	yield image_id
	yield was_quantized, design_id

def create_basic_design(design, *, scale: bool):
	"""Upload a basic design. Scale controls whether to tile or scale the image. Returns an iterable of design IDs."""
	image = design.layer_images['0']
	images = get_images(image, scale=scale)

	# XXX is it a Design class or an Image class. It's both! Is that OK?
	image_id = pg().fetchval(
		queries.create_image(),

		session['user_id'],
		design.author_name,
		design.design_name,
		image.width,
		image.height,
		'scale' if scale else 'tile',
		design.type_code,
		[bytearray(image.export_pixels())],
	)
	yield image_id
	images = list(zip(reversed(range(1, len(images) + 1)), reversed(images)))
	yield from create_designs(image_id, design, images, tile=not scale)

def create_designs(image_id, design, images, *, tile: bool):
	for count, (i, image) in enumerate(images, 1):
		design_name = f'{design.design_name} {i}' if tile else design.design_name
		sub_design = encode.BasicDesign(
			design_name=design_name,
			island_name=design.island_name,
			author_name=design.author_name,
			layers={'0': image},
		)
		# we do this on each loop in case someone uploaded a few more designs in between iterations
		garbage_collect_designs(len(images) - (count - 1), pro=False)
		# designs get out of order if we post them too fast
		time.sleep(0.5)
		was_quantized, encoded = encode.encode(sub_design)
		design_id = api.create_design(encoded)
		create_design(image_id=image_id, design_id=design_id, position=i, pro=False)
		yield was_quantized, design_id

def get_images(image, *, scale: bool):
	if image.size > SIZE and not scale:
		TiledImageTooBigError.validate(image)
		# backwards so that the first image shows up first in game
		return list(encode.tile(image.clone()))[::-1]

	# scale if necessary
	return [image.clone()]

def refresh_image(image_id):
	rows = pg().fetch(queries.image_with_designs(), image_id)
	if not rows:
		raise UnknownImageIdError
	image_info = rows[0]
	required_design_count = 1 if image_info['pro'] else num_tiles(image_info['width'], image_info['height'])
	if len(rows) == required_design_count:
		return None

	design_positions = {row['position'] for row in rows}
	required_positions = set(range(1, required_design_count + 1))
	missing_positions = required_positions - design_positions
	cls = encode.Design(image_info['type_code'])
	if image_info['pro']:
		# TODO deduplicate this from views/frontend.py
		layers = {}
		for layer_def, blob in zip(cls.external_layers, image_info['layers']):
			layers[layer_def.name] = img = layer_def.as_wand()
			layer_def.import_pixels(data=blob, channel_map='RGBA')

		design = cls(layers=layers, island_name=island_name(), design_name=image_info['image_name'])
		was_quantized, encoded = encode.encode(design)
		design_id = api.create_design(encoded)
		create_design(image_id=image_id, design_id=design_id, position=0, pro=True)
		yield was_quantized, design_id
	else:
		img = wand.image.Image(width=image_info['width'], height=image_info['height'])
		img.import_pixels(data=image_info['layers'][0], channel_map='RGBA')
		design = encode.BasicDesign(layers={'0': img}, design_name=image_info['image_name'], island_name=island_name())
		images = get_images(img, scale=image_info['mode'] == 'scale')
		to_create = [(i, img) for i, img in enumerate(images, 1) if i in missing_positions]
		yield from create_designs(image_id, design, to_create, tile=image_info['mode'] == 'tile')

def create_design(*, image_id, design_id, position, pro):
	pg().execute(queries.create_design(), image_id, design_id, position, pro)

def image(image_id):
	rows = pg().fetch(queries.image_with_designs(), image_id)
	if not rows:
		raise UnknownImageIdError
	image = dict(rows[0])
	# these are design fields not image fields
	del image['design_id'], image['position']
	designs = []
	for row in rows:
		if row['design_id'] is None:
			break

		design = {}
		designs.append(design)
		design['design_id'] = row['design_id']
		design['design_code'] = api.design_code(row['design_id'])
		design['position'] = row['position']
	return {'image': image, 'designs': designs}
