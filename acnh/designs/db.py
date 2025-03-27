# © 2020 io mintz <io@mintz.cc>

import enum
import random
import time
from dataclasses import dataclass, field
from functools import partial
from typing import List, Generic, TypeVar, Optional

import anyio
import wand.image
from quart import request

from . import api, encode
from .format import SIZE, MAX_DESIGN_TILES
from utils import pg, queries
from ..errors import UnknownImageIdError, DeletionDeniedError, TiledImageTooBigError, ImageNameTooLongError, num_tiles

ISLAND_NAMES = [
	'The Cloud',
	'Black Lives Matter',
	'ACAB',
]

island_name = partial(random.choice, ISLAND_NAMES)

class PageDirection(enum.Enum):
	before = -1
	after = +1

T = TypeVar('T')

@dataclass
class PageSpecifier(Generic[T]):
	direction: PageDirection
	reference: Optional[T]
	limit: Optional[int] = field(default=None)

	# convenience factories

	@classmethod
	def first(cls):
		return cls(PageDirection.after, None)

	@classmethod
	def last(cls):
		return cls(PageDirection.before, None)

	@classmethod
	def after(cls, reference: T) -> 'PageSpecifier[T]':
		return cls(PageDirection.after, reference)

	@classmethod
	def before(cls, reference: T) -> 'PageSpecifier[T]':
		return cls(PageDirection.before, reference)

async def garbage_collect_designs(needed_slots: int, *, pro: bool):
	"""Free at least needed_slots. Pass pro depending on whether Pro slots are needed."""
	design_ids = [hdr['id'] for hdr in await api.stale_designs(needed_slots, pro=pro)]
	if not design_ids:
		return

	print('GC', len(design_ids), 'designs')
	# we would do this in parallel but we'd rather not get banned lol
	for design_id in design_ids:
		await api.delete_design(design_id)

	tag = await current_app.pg.execute(queries.delete_designs(), design_ids)
	if tag != f'DELETE {len(design_ids)}':
		print('One or more stale design IDs were found in the API but not in the database! Ignoring…')

async def delete_image(image_id):
	image_author_id = await current_app.pg.fetchval(queries.image_author_id(), image_id)
	valid = image_author_id == request.user_id
	if image_author_id is None:
		raise UnknownImageIdError
	if not valid:
		raise DeletionDeniedError

	async with current_app.pg.transaction(isolation='serializable'):
		design_ids = await current_app.pg.fetchvals(queries.delete_image_designs(), image_id)
		await current_app.pg.execute(queries.delete_image(), image_id)

	for design_id in design_ids:
		await api.delete_design(design_id)

async def create_image(design, **kwargs):
	return await (create_pro_design if design.pro else create_basic_design)(design, **kwargs)

async def create_pro_design(design):
	"""Upload a pro design. Returns an iterable for consistency with create_basic_design."""
	was_quantized, encoded = encode.encode(design)
	await garbage_collect_designs(1, pro=True)
	image_id = await current_app.pg.fetchval(
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
	design_id = await api.create_design(encoded)
	await create_design(image_id=image_id, design_id=design_id, position=1, pro=True)
	yield image_id
	yield was_quantized, design_id

async def create_basic_design(design, *, scale: bool):
	"""Upload a basic design. Scale controls whether to tile or scale the image. Returns an iterable of design IDs."""
	image = design.layer_images['0']
	images = split_images(design, scale=scale)

	# XXX is it a Design class or an Image class. It's both! Is that OK?
	image_id = await current_app.pg.fetchval(
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
	async for x in create_designs(image_id, design, images, tile=not scale):
		yield x

async def create_designs(image_id, design, images, *, tile: bool):
	await garbage_collect_designs(len(images), pro=False)
	for count, (i, image) in enumerate(images, 1):
		design_name = f'{design.design_name} {i}' if tile else design.design_name
		sub_design = encode.BasicDesign(
			design_name=design_name,
			island_name=design.island_name,
			author_name=design.author_name,
			layers={'0': image},
		)
		# we do this on each loop in case someone uploaded a few more designs in between iterations
		await garbage_collect_designs(len(images) - (count - 1), pro=False)
		# designs get out of order if we post them too fast
		await anyio.sleep(0.5)
		was_quantized, encoded = encode.encode(sub_design)
		design_id = await api.create_design(encoded)
		await create_design(image_id=image_id, design_id=design_id, position=i, pro=False)
		yield was_quantized, design_id

def split_images(design: encode.BasicDesign, *, scale: bool):
	image = design.layer_images['0']
	if image.size > SIZE and not scale:
		TiledImageTooBigError.validate(image)
		ImageNameTooLongError.validate(design)
		return list(encode.tile(image))

	# scale if necessary
	return [image.clone()]

async def refresh_image(image_id):
	rows = await current_app.pg.fetch(queries.image_with_designs(), image_id)
	if not rows:
		raise UnknownImageIdError
	image_info ,= rows
	required_design_count = 1 if image_info['pro'] else num_tiles(image_info['width'], image_info['height'])
	if len(rows) == required_design_count:
		return

	if image_info['pro']:
		gen = refresh_pro_image(image_info)
	else:
		gen = refresh_basic_image(rows)

	for x in gen:
		yield x

def gather_layers(cls, layers: List[wand.image.Image]):
	named_layers = {}
	for layer_def, blob in zip(cls.external_layers, layers):
		named_layers[layer_def.name] = img = layer_def.as_wand()
		img.import_pixels(data=blob, channel_map='RGBA')
	return named_layers

async def refresh_pro_image(image_info):
	cls = encode.Design(image_info['type_code'])
	layers = gather_layers(cls, image_info['layers'])

	# pylint: disable=not-callable
	design = cls(layers=layers, island_name=island_name(), design_name=image_info['image_name'])
	was_quantized, encoded = encode.encode(design)
	design_id = await api.create_design(encoded)
	await create_design(image_id=image_info['image_id'], design_id=design_id, position=0, pro=True)
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
	images = split_images(design, scale=image_info['mode'] == 'scale')
	to_create = [(i, img) for i, img in enumerate(images, 1) if i in missing_positions]
	yield from create_designs(image_info['image_id'], design, to_create, tile=image_info['mode'] == 'tile')

async def create_design(*, image_id, design_id, position, pro):
	await current_app.pg.execute(queries.create_design(), image_id, design_id, position, pro)

async def image(image_id):
	rows = await current_app.pg.fetch(queries.image_with_designs(), image_id)
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

ImageId = int

MAX_PAGE_SIZE = MAX_DESIGN_TILES

async def images_keyset(page: PageSpecifier[ImageId] = PageSpecifier.first(), *, debug=False):
	limit = page.limit
	if limit is None:
		limit = MAX_PAGE_SIZE
	args = [min(max(limit, 1), MAX_PAGE_SIZE)]
	kwargs = dict(sort_order='DESC' if page.direction is PageDirection.before else 'ASC')
	if page.reference is not None:
		args.append(page.reference)
	else:
		kwargs['end'] = True

	if debug:
		return queries.images_keyset(**kwargs), args

	images = await current_app.pg.fetch(queries.images_keyset(**kwargs), *args)
	if page.direction is PageDirection.before:
		images.reverse()
	return images

@api.accepts_design_id
async def design_image(design_id):
	return await current_app.pg.fetchrow(queries.design_image(), design_id)
