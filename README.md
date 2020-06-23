# Plaza

This is a REST API and web frontend for programmatic access to Dodo Codes and Custom Designs.
My instance is available at:
- https://acplaza.app
- http://acnhok4pb2e6jwy2khjollqznnkrqxpt5toaknjrqdfeqir3iqhyl6ad.onion/

This API requires paid authorization.
If you would like access, please [subscribe on Patreon](https://patreon.com/iomintz) for at least $5 / month.
After you pay I will message you a token via Patreon. Send this token as the value of the `Authorization` header
in all requests.

## Endpoints

The prefix for all endpoints is `/api/v0`. This means the full path for /design/1 is `/api/v0/design/1`.

### Dodo Codes

- /host-session/:dodo-code
Returns info about an active island hosting session.

### Custom Designs

The /design endpoints take an optional `scale` query parameter, an integer 1–6 which scales the image
using what is believed to be the same algorithm that the game uses.

- /design/:custom-design-code
  Returns the unprocessed response from Nintendo's servers. Contains the raw data for the image along with its palette
  and creator information. Binary data (`resp.mData.mData`) is base64 encoded.
- /design/:custom-design-code.tar
  Returns a tar archive containing a PNG render of each layer of the given custom design code.
  Query parameters:
  - `?internal`: returns the internal layers (0, 1, 2, or 3) instead of the human-friendly ones
    (e.g. 'front', 'back', 'brim').
- /design/:custom-design-code/:layer.png
  Returns a PNG render of the specified layer. This can be a human-friendly layer, an internal layer, or the special
  `thumbnail` layer which generates a preview of the design. Thumbnails cannot be scaled.
- /designs/:creator-id Lists the designs posted by the given creator ID. Query parameters:
  - pro: true/false. whether to list the creator's Pro designs only. If false only normal designs will be listed.

### Images

“Images” are a concept specific to this software which represent one large image tiled, scaled, or quantized into 
one or more in-game designs.

- POST /images<br>
  Query parameters:
  - `image_name`
  - `author_name`
  - `scale`: whether to scale the image if it's larger than 32×32. Only valid if `design_type` is `basic_design`.
    If false (the default) then the image will be tiled into multiple designs.
  - `resize`: resize the image in an aspect-ratio preserving way before any other processing. Only valid if
    `scale` is false. Useful for tiling large images.
  - `design_type`: required. Defaults to `basic-design` (ie a non-Pro design). Valid options:
  The image data must be uploaded as `multipart/form-data`, with each file name corresponding to a layer name.
  A wide variety of image formats may be used (anything that ImageMagick supports).
  The response for this endpoint is streamed as text/plain. The first line of the stream is the resulting image ID.
  Each subsequent line is formatted like `was_quantized,design_code`. For example: `0,5RJJ-TXK3-JWXV`.
- GET /image/:image-id
  Returns a JSON object with two keys: `image` and `design`. For example:

```json
{
	"image": {
		"image_id": 9,
		"author_name": "Anonymous",
		"image_name": "Droon Fox",
		"created_at": "2020-06-18T02:08:19.468474+00:00",
		"width": 128,
		"height": 128,
		"mode": "tile",
		"layers": [
			"base64 encoded image",
			"base64 encoded image2",
			"etc"
		],
		"pro": false,
		"design_type": "basic-design"
	},
	"designs": [
		{
			"design_id": 337936614208352244,
			"design_code": "M28X-QT1R-HM4S",
			"position": 2
		},
		{
			"design_id": 338686262569391946,
			"design_code": "M3K1-B98K-86L6",
			"position": 3
		}
	]
}
```

- POST /image/:image-id/refresh
  If some of the designs for an image were deleted to save space, this endpoint will re-create them, and
  return their design codes in the same format as POST /images will, but without the initial header line.

### Valid Design Types

The names of the layers for these design types are used as the filename for each part in the `multipart/form-data`
upload. For example, to use `curl` to upload a Brimmed Hat:

```
curl \
	-H "Authorization: $ACNH_TOKEN" \
	-F top=@top.png \
	-F middle=@middle.png \
	-F bottom=@bottom.png \
	'https://acplaza.app/images?design_type=brimmed-hat&image_name=My%20Brimmed%20Hat&author_name=iomintz'
```

- basic-design: a single 32×32 layer, called `0`. The singular non-Pro design type.
- tank-top: 2 layers: `front` and `back`. Both 32×32.
- short-sleeve-tee: same as tank-top with two additional layers, `right-sleeve` and `left-sleeve`, both 22×13.
- long-sleeve-dress-shirt: same as tank-top with two additional layers: `right-sleeve` and `left-sleeve`, both 22×22.
- sweater: same as long-sleeve-dress-shirt.
- hoodie: same as long-sleeve-dress-shirt.
- coat: four layers: `back`, `front`, `right-sleeve`, and `left-sleeve`. Back / front are 32×41. Sleeves are 22×22.
- sleeveless-dress: two layers: `back`, and `front`, both 32×41.
- short-sleeve-dress: same as sleeveless-dress, with two additional layers: `right-sleeve` and `left-sleeve`, both 22×13.
- long-sleeve-dress: same as coat.
- round-dress: same as short-sleeve-dress.
- balloon-hem-dress: same as short-sleeve-dress.
- robe: same as sleeveless-dress, with two additional layers: `right-sleeve` and `left-sleeve`, both 30×22.
- brimmed-cap: three layers: `front` (44×41), `back` (20×44), and `brim` (44×21).
- knit-cap: one layer: `cap` (64×53)
- brimmed-hat: three layers: `top` (36×36), `middle` (64×19), and `bottom` (64×9)

## Errors

Here's an example error response:

```json
{
	"error": "invalid dodo code",
	"error_code": 102,
	"http_status": 400,
	"validation_regex": "[A-HJ-NP-Y0-9]{5}"
}
```

All error responses are guaranteed to have at least the `error`, `error_code`, and `http_status` keys, so the
presence of these fields is a reliable indicator of an error. `error_code` is an integer where `error_code / 100`
indicates the error category, similarly to HTTP. Unlike HTTP, `error_code % 100 == 0` is reserved for successful statuses.
String format errors are guaranteed to have a `validation_regex` field.

Error code | Description
------------------------
**1xx** | **Dodo Code™ errors**
101 | Unknown Dodo Code™
102 | Invalid Dodo Code™
**2xx** | **Design errors**
201 | Unknown design code
202 | Invalid design code
203 | Unknown author ID
204 | Invalid author ID
205 | Invalid scale factor
206 | Invalid layer index
207 | Invalid argument for the `pro` query parameter
208 | Cannot scale thumbnails
209 | Invalid design (raised when Nintendo rejects an uploaded design)
210 | Invalid palette (the image(s) uploaded were not constrained to 15 colors + transparent)
**3xx** | **Image errors**
301 | Unknown image ID
302 | Invalid image ID
303 | Image deletion denied
304 | A single layer is required, more than one was passed
305 | One or more layers were of an invalid size
306 | The uploaded image would exceed 16 tiles
307 | A required image argument was missing or invalid
308 | One or more layer names passed was invalid
309 | One or more layers were missing
310 | One or more layers were not a valid image file
**9xx** | General API errors**
901 | Missing User-Agent header
902 | Invalid or incorrect Authorization header

## Setup

First copy config.example.toml to config.toml. Now you will need a lot of information from your Switch
and eShop obtained copy of Animal Crossing: New Horizons.
If you're buying the game just for this API, it's recommended to use a different Nintendo account than the one
you play Animal Crossing on normally, so that the API can be used while you're playing.

### Obtaining your credentials

1. Use [Lockpick_RCM](https://github.com/shchmue/Lockpick_RCM/releases)
   to obtain your prod.keys file and copy it to ~/.switch/prod.keys.
2. In Hekate, make a full backup of your Switch's NAND.
3. Install [ninfs](https://github.com/ihaveamac/ninfs) and use this command to mount your backup:
   `mount_nandhac -S rawnand.bin.00 /path/to/mountpoint`
4. Copy PRODINFO.img from your mountpoint to somewhere safe.
5. Mount SYSTEM.img as a FAT32 filesystem.
6. Using [hactoolnet](https://github.com/Thealexbarney/LibHac/releases), extract the `save/8000000000000010`
   file from your SYSTEM.img mountpoint using the following command:
   `hactoolnet -t save --outdir 8000000000000010-extracted /path/to/system.img-mountpoint/save/8000000000000010`.
7. `8000000000000010-extracted/su/baas/<guid>.dat` contains your BAAS user ID and password (your GUID will differ).
   The following python code will extract it:

```py
with open('/path/to/<guid>.dat', 'rb') as f:
	f.seek(0x20)
	print('BAAS user ID:', hex(int.from_bytes(f.read(8), byteorder='little')))
	print('BAAS password:', f.read(40).decode('ascii'))
```

8. Use [nxdumptool](https://github.com/DarkMatterCore/nxdumptool/releases) to dump your AC:NH ticket.
   You must have the eShop version to proceed. Game cards are not supported. 
   Use nxdumptool to dump the base ticket (not the update ticket) for the game.
9. Dump your save file using [JKSV](https://github.com/J-D-K/JKSV/releases).
   Use [effective-guacamole](https://github.com/3096/effective-guacamole) to decrypt your save file.
   Your ACNH user ID and password are contained in the VillagerN/personal.dat file after decryption.
   Use the following python code to extract it:

```py
with open('Villager0/personal.dat.dec', 'rb') as f:
	f.seek(0x6B838)
	print('ACNH User ID:', hex(int.from_bytes(f.read(8), 'little')))
	print('ACNH Password:', f.read(64).decode('ascii'))
```

10. Edit config.toml according to the information and files you retrieved.

## License

Business Source License, v1.1. See LICENSE for details.

The license as of 94d7fa2a8ea4096bd1ae981f1b53444966ec2198 applies to commits before
94d7fa2a8ea4096bd1ae981f1b53444966ec2198 as well, regardless of the license stated in that
commit.

### Additional terms / credits

- Most of the work of figuring out the image format was done by Josh#6734 and Cute#0313 on Discord.
- Cute assisted with writing the image encoding code.
- Ava#4982 figured out the Design Code alphanumeric format.
- @The0x539 assisted with figuring out how to specify the conversions between internal and external layers for
  Pro designs.

- acnh/common.py is based on code provided by Yannik Marchand, used under the MIT License.
  See that file for details.
- acnh/designs/render.py is based on code provided by @nickwanninger
  and copyright ownership has been transferred to me, io mintz.
- tarfile_stream.py is based on the Python standard library tarfile.py and used under the MIT License.
  See that file for details.
