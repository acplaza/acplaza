# © 2020 io mintz <io@mintz.cc>

# ACNH API is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# ACNH API is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with ACNH API. If not, see <https://www.gnu.org/licenses/>.

import io

import wand.image
import wand.color

NET_IMAGE_INNER_WIDTH = NET_IMAGE_INNER_HEIGHT = 230
NET_IMAGE_BORDER_SIZE = 5

def net_image(img):
	net_img = img.clone()
	net_img.scale(NET_IMAGE_INNER_WIDTH, NET_IMAGE_INNER_HEIGHT)
	net_img.border(wand.color.Color('#f3f5e7'), NET_IMAGE_BORDER_SIZE, NET_IMAGE_BORDER_SIZE)
	net_img.convert('JPG')
	return net_img

with open('data/preview image template.jpg', 'rb') as f:
	preview_image_template = f.read()

def preview_image(img):
	preview_img = wand.image.Image(blob=preview_image_template)
	with img.clone() as img:
		preview_img.sequence.append(img)
		preview_img.distort('perspective', (
			0, 0, 141, 58,
			32, 0, 387, 76,
			0, 32, 119, 317,
			32, 32, 367, 334
		))
		preview_img.convert('JPG')
	return preview_img
