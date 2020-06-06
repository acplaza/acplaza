# ACNH API

This is a REST API for programmatic access to Dodo Codes and Custom Designs.

## Endpoints

### Dodo Codes

- /host-session/:dodo-code
Returns info about an active island hosting session.

### Custom Designs

These endpoints take an optional `scale` parameter, an integer 1–6 which scales the image
using what is believed to be the same algorithm that the game uses.

- /design/:custom-design-code
Returns the unprocessed response from Nintendo's servers. Contains the raw data for the image along with its palette
and creator information. Binary data (`resp.mData.mData`) is base64 encoded.
- /design/:custom-design-code.tar
Returns a tar archive containing a PNG render of each layer of the given custom design code.
- /design/:custom-design-code/:layer.png
Returns a PNG render of the specified layer.

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
9. Install these FS patches on your switch in order to disable CA Verficiation. https://github.com/misson20000/exefs_patches/tree/master/atmosphere/exefs_patches/disable_ca_verification
10. Set up a web proxy such as Charles. Configure your Switch's network settings to proxy through your web proxying software. 11. Intercept your Switch's request to https://api.hac.lp1.acbaa.srv.nintendo.net/api/v1/auth_token. The request body contains a msgpack encoded dictionary like this: `{'id': 1311768467445894639, 'password': '64 characters here'}`. This user ID and password goes in the config as `acnh-user-id` and `acnh-password`.
12. Edit config.toml according to the information and files you retrieved.

## License

AGPLv3 or later, see LICENSE.md.

### Additional terms / credits

- acnh/common.py is based on code provided by Yannik Marchand, used under the MIT License.
See that file for details.
- acnh/design_render.py is provided by @nickwanninger under the AGPLv3 or later license.
- tarfile_stream.py is based on the Python standard library tarfile.py and used under the MIT License.
See that file for details.
- xbrz/ is based on code provided by Zenju under the GPLv3 license.
