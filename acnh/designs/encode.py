# © 2020 io mintz <io@mintz.cc>

import io
import itertools
import random
import struct

import wand.image
import msgpack

from .. import utils
from .format import PALETTE_SIZE, WIDTH, HEIGHT, SIZE

with open('data/net image.jpg', 'rb') as f:
	dummy_net_image = f.read()
with open('data/preview image.jpg', 'rb') as f:
	dummy_preview_image = f.read()

LITTLE_ENDIAN_UINT32 = struct.Struct('>L')
TWO_LITTLE_ENDIAN_UINT32S = struct.Struct('>LL')

def tile(image):
	num_v_segments = image.width // WIDTH
	num_h_segments = image.height // HEIGHT
	# y, x so that the images are in row-major order not column-major order,
	# which is how most people expect iamges to be tiled
	for y, x in itertools.product(
		range(0, image.height, HEIGHT),
		range(0, image.width, WIDTH),
	):
		yield image[x:min(image.width, x+WIDTH), y:min(image.height, y+HEIGHT)]


def encode(island_name, design_name, image: wand.image.Image) -> dict:
	encoded = {}
	meta = {'mMtVNm': island_name, 'mMtDNm': design_name, 'mMtNsaId': random.randrange(2**64), 'mMtVer': 2306, 'mAppReleaseVersion': 7, 'mMtVRuby': 2, 'mMtUse': 99, 'mMtTag': [0, 0, 0], 'mMtPro': False, 'mMtLang': 'en-US', 'mPHash': 0, 'mShareUrl': ''}
	encoded['meta'] = msgpack.dumps(meta)

	image = image.clone()
	if image.size > SIZE:
		# preserve aspect ratio
		image.transform(resize=f'{WIDTH}x{HEIGHT}')
	if image.size != SIZE:
		# Due to the ACNH image format not containing size information, all images must be exactly
		# the same size. Otherwise, the image has extra space at the *bottom*, not necessarily on the
		# side, as may be the case with this image.
		base_image = wand.image.Image(width=WIDTH, height=HEIGHT)
		base_image.background_color = wand.color.Color('rgba(0, 0, 0, 0)')
		base_image.sequence.append(image)
		base_image.merge_layers('flatten')
		image = base_image

	if image.colors > PALETTE_SIZE - 1:
		image.quantize(number_colors=PALETTE_SIZE - 1)

	if image.colors > PALETTE_SIZE - 1:
		raise RuntimeError(
			f'generated palette has more than {PALETTE_SIZE} colors ({image.colors}) even after quantization!'
		)

	with image:
		# casting to a memoryview should ensure efficient slicing
		pxs = memoryview(bytearray(image.export_pixels(storage='char', channel_map='RGBA')))

	# determine the palette
	palette = {}
	color_i = 0
	for px in utils.chunked(pxs, 4):
		color, = LITTLE_ENDIAN_UINT32.unpack(px)
		if color not in palette:
			palette[color] = color_i
			color_i += 1

	if len(palette) > PALETTE_SIZE - 1:
		raise RuntimeError(
			f'generated palette has more than {PALETTE_SIZE} colors ({len(palette)}) even after quantization!'
		)

	# actually encode the image
	img = io.BytesIO()
	for pixels in utils.chunked(pxs, 8):
		px1, px2 = TWO_LITTLE_ENDIAN_UINT32S.unpack_from(pixels)
		img.write((palette[px2] << 4 | palette[px1]).to_bytes(1, byteorder='big'))

	data = {}
	data['mMeta'] = meta
	data['mData'] = img_data = {}

	palette = img_data['mPalette'] = {str(i): color for color, i in palette.items()}
	# implicit transparent
	palette[str(PALETTE_SIZE - 1)] = 0

	img_data['mData'] = {'0': img.getvalue()}
	img_data['mAuthor'] = {'mVId': 4255292630, 'mPId': 2422107098, 'mGender': 0}
	img_data['mFlg'] = 2
	img_data['mClSet'] = 238

	encoded['body'] = msgpack.dumps(data)
	encoded['net_image'] = dummy_net_image
	encoded['preview_image'] = dummy_preview_image

	return encoded
