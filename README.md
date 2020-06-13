# ACNH API

This is a REST API for programmatic access to Dodo Codes and Custom Designs. My instance is available at:
- https://acnh-api.ashitty.website
- http://acnhok4pb2e6jwy2khjollqznnkrqxpt5toaknjrqdfeqir3iqhyl6ad.onion/

This API requires paid authorization.
If you would like access, please [subscribe on Patreon](https://patreon.com/iomintz) for at least $5 / month.
After you pay I will message you a token via Patreon. Send this token as the value of the `Authorization` header
in all requests.

## Endpoints

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
  Returns a PNG render of the specified layer.
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

### Valid Design Types

The names of the layers for these design types are used as the filename for each part in the `multipart/form-data`
upload. For example, to use `curl` to upload a Brimmed Hat:

```
curl \
	-H "Authorization: $ACNH_TOKEN" \
	-F top=@top.png \
	-F middle=@middle.png \
	-F bottom=@bottom.png \
	'https://acnh-api.ashitty.website/images?design_type=brimmed-hat&image_name=My%20Brimmed%20Hat&author_name=iomintz'
```

**TODO finish documenting these**

- basic-design: a single 32×32 layer, called `0`. The singular non-Pro design type.
- tank-top: 2 layers: `front` and `back`.
- short-sleeve-tee
- long-sleeve-dress-shirt
- sweater
- hoodie
- coat
- sleeveless-dress
- short-sleeve-dress
- long-sleeve-dress
- round-dress
- balloon-hem-dress
- robe
- brimmed-cap
- knit-cap
- brimmed-hat

## Setup

First copy config.example.toml to config.toml. Now you will need a lot of information from your Switch
and eShop obtained copy of Animal Crossing: New Horizons.
If you're buying the game just for this API, it's recommended to use a different Nintendo account than the one
you play Animal Crossing on normally, so that the API can be used while you're playing.

You'll also need to compile the xBRZ scaling library. Don't worry, it has no deps. Just run `make -C xbrz`.

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
9. Install these FS patches on your switch in order to disable CA Verification:
   https://github.com/misson20000/exefs_patches/tree/master/atmosphere/exefs_patches/disable_ca_verification
10. Set up a web proxy such as Charles.
    Configure your Switch's network settings to proxy through your web proxying software.
11. In game, log on to the Custom Designs kiosk at the Able Sister's shop.
    Then intercept your Switch's request to https://api.hac.lp1.acbaa.srv.nintendo.net/api/v1/auth_token.
    The request body contains a msgpack encoded dictionary like this:
    `{'id': 1311768467445894639, 'password': '64 characters here'}`.
    This user ID and password goes in the config as `acnh-user-id` and `acnh-password`.
12. Edit config.toml according to the information and files you retrieved.

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
