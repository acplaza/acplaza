# © 2020 io mintz <io@mintz.cc>

import io
import itertools
import struct
import wand.image
import msgpack

from . import utils
from .format import PALETTE_SIZE, WIDTH, HEIGHT, SIZE

with open('data/net image.jpg', 'rb') as f:
	dummy_net_image = f.read()
with open('data/preview image.jpg', 'rb') as f:
	dummy_preview_image = f.read()

LITTLE_ENDIAN_UINT32 = struct.Struct('>L')

def chop(image):
	num_segments = image.width // WIDTH
	segment_width = image.width // num_segments
	for x, y in itertools.product(range(0, image.width, segment_width), repeat=2):
		yield image[x:x+segment_width, y:y+segment_width]

def encode(name, image: wand.image.Image) -> dict:
	encoded = {}
	meta = {'mMtVNm': 'ACNH API', 'mMtDNm': name, 'mMtVer': 2306, 'mAppReleaseVersion': 7, 'mMtVRuby': 2, 'mMtUse': 99, 'mMtTag': [0, 0, 0], 'mMtPro': False, 'mMtNsaId': 6345768839027671582, 'mMtLang': 'en-US', 'mPHash': 0, 'mShareUrl': ''}
	encoded['meta'] = msgpack.dumps(meta)
	with image.clone() as image:
		if image.size > SIZE:
			image.scale(*SIZE)
		if image.colors > PALETTE_SIZE:
			print('quantizing')
			image.quantize(number_colors=PALETTE_SIZE, dither='no')
		pxs = memoryview(bytearray(image.export_pixels(storage='char', channel_map='RGBA')))

	palette = {}
	palette_idx = 0
	for px in utils.chunked(pxs, 4):
		color, = LITTLE_ENDIAN_UINT32.unpack(px)
		if color not in palette:
			palette[color] = palette_idx
			palette_idx += 1

	if len(palette) > PALETTE_SIZE:
		raise RuntimeError(
			f'generated palette has more than {PALETTE_SIZE} colors ({len(palette)}) even after quantization!'
		)

	# actually encode the image
	img = io.BytesIO()
	for pixels in utils.chunked(pxs, 8):
		px1, = LITTLE_ENDIAN_UINT32.unpack_from(pixels)
		px2, = LITTLE_ENDIAN_UINT32.unpack_from(pixels, offset=4)
		img.write((palette[px1] << 4 | palette[px2]).to_bytes(1, byteorder='big'))

	data = {}
	data['mMeta'] = meta
	data['mData'] = img_data = {}
	img_data['mPalette'] = {str(i): color for color, i in palette.items()}
	img_data['mData'] = {'0': img.getvalue()}
	img_data['mAuthor'] = {'mVId': 4255292630, 'mPId': 2422107098, 'mGender': 0}
	img_data['mFlg'] = 2
	img_data['mClSet'] = 238

	encoded['body'] = msgpack.dumps(data)
	encoded['net_image'] = dummy_net_image
	encoded['preview_image'] = dummy_preview_image

	return encoded
