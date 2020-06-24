# © 2020 io mintz <io@mintz.cc>

import random
import time
from functools import partial
from typing import List

import wand.image
from flask import request

from . import api, encode
from .format import SIZE
from utils import pg, queries
from ..errors import UnknownImageIdError, DeletionDeniedError, TiledImageTooBigError, num_tiles

ISLAND_NAMES = [
	'The Cloud',
	'Black Lives Matter',
	'ACAB',
]

island_name = partial(random.choice, ISLAND_NAMES)

def garbage_collect_designs(needed_slots: int, *, pro: bool):
	"""Free at least needed_slots. Pass pro depending on whether Pro slots are needed."""
	design_ids = [hdr['id'] for hdr in api.stale_designs(needed_slots, pro=pro)]
	if not design_ids:
		return

	for design_id in design_ids:
		api.delete_design(design_id)

	tag = pg().execute(queries.delete_designs(), design_ids)
	if tag != f'DELETE {len(design_ids)}':
		print('One or more stale design IDs were found in the API but not in the database! Ignoring…')

def delete_image(image_id):
	image_author_id = pg().fetchval(queries.image_author_id(), image_id)
	valid = image_author_id == request.user_id
	if image_author_id is None:
		raise UnknownImageIdError
	if not valid:
		raise DeletionDeniedError

	with pg().transaction(isolation='serializable'):
		design_ids = pg().fetchvals(queries.delete_image_designs(), image_id)
		pg().execute(queries.delete_image(), image_id)

	for design_id in design_ids:
		api.delete_design(design_id)

def create_image(design, **kwargs):
	return (create_pro_design if design.pro else create_basic_design)(design, **kwargs)

def create_pro_design(design):
	"""Upload a pro design. Returns an iterable for consistency with create_basic_design."""
	was_quantized, encoded = encode.encode(design)
	garbage_collect_designs(1, pro=True)
	image_id = pg().fetchval(
		queries.create_image(),

		request.user_id,
		design.author_name,
		design.design_name,
		None,  # width
		None,  # height
		None,  # mode
		design.type_code,
		[bytearray(image.export_pixels()) for image in design.layer_images.values()],
	)
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

		request.user_id,
		design.author_name,
		design.design_name,
		image.width,
		image.height,
		'scale' if scale else 'tile',
		design.type_code,
		[bytearray(image.export_pixels())],
	)
	yield image_id
	# backwards so that the first image shows up first in game
	images = list(zip(reversed(range(1, len(images) + 1)), reversed(images)))
	yield from create_designs(image_id, design, images, tile=not scale)

def create_designs(image_id, design, images, *, tile: bool):
	garbage_collect_designs(len(images), pro=False)
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
		return list(encode.tile(image))

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

	if image_info['pro']:
		yield from refresh_pro_image(image_info)
	else:
		yield from refresh_basic_image(rows)

def gather_layers(cls, layers: List[wand.image.Image]):
	named_layers = {}
	for layer_def, blob in zip(cls.external_layers, layers):
		named_layers[layer_def.name] = img = layer_def.as_wand()
		img.import_pixels(data=blob, channel_map='RGBA')
	return named_layers

def refresh_pro_image(image_info):
	cls = encode.Design(image_info['type_code'])
	layers = gather_layers(cls, image_info['layers'])

	# pylint: disable=not-callable
	design = cls(layers=layers, island_name=island_name(), design_name=image_info['image_name'])
	was_quantized, encoded = encode.encode(design)
	design_id = api.create_design(encoded)
	create_design(image_id=image_info['image_id'], design_id=design_id, position=0, pro=True)
	yield was_quantized, design_id

def refresh_basic_image(rows):
	image_info = rows[0]
	required_design_count = num_tiles(image_info['width'], image_info['height'])

	design_positions = {row['position'] for row in rows}
	required_positions = set(range(1, required_design_count + 1))
	missing_positions = required_positions - design_positions

	img = wand.image.Image(width=image_info['width'], height=image_info['height'])
	img.import_pixels(data=image_info['layers'][0], channel_map='RGBA')
	design = encode.BasicDesign(layers={'0': img}, design_name=image_info['image_name'], island_name=island_name())
	images = get_images(img, scale=image_info['mode'] == 'scale')
	to_create = [(i, img) for i, img in enumerate(images, 1) if i in missing_positions]
	yield from create_designs(image_info['image_id'], design, to_create, tile=image_info['mode'] == 'tile')

def create_design(*, image_id, design_id, position, pro):
	pg().execute(queries.create_design(), image_id, design_id, position, pro)

def image(image_id):
	rows = pg().fetch(queries.image_with_designs(), image_id)
	if not rows:
		raise UnknownImageIdError
	image = dict(rows[0])
	# these are design fields not image fields
	del image['design_id'], image['position']
	designs = {}
	for row in rows:
		if row['design_id'] is None:
			break
		designs[row['position']] = api.design_code(row['design_id'])

	return {'image': image, 'designs': designs}

@api.accepts_design_id
def design_image(design_id):
	return pg().fetchrow(queries.design_image(), design_id)
