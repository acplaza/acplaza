# ACNH API

This is a REST API for programmatic access to Dodo Codes and Custom Designs.

## Endpoints

- /host-session/:dodo-code
Returns info about an active island hosting session.
- /design/:custom-design-code
Returns the unprocessed response from Nintendo's servers. Contains the raw data for the image along with its palette
and creator information. Binary data (`resp.mData.mData`) is base64 encoded.
- /design/:custom-design-code.tar
Returns a tar archive containing a PNG render of each layer of the given custom design code.

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

8. Lastly you will need to use [nxdumptool](https://github.com/DarkMatterCore/nxdumptool/releases) to dump your AC:NH
   ticket. You must have the eShop version to proceed. Game cards are not supported. Use nxdumptool to dump the
   base ticket (not the update ticket) for the game.
9. Edit config.toml according to the information and files you retrieved.

## License

AGPLv3 or later, see LICENSE.md.

### Additional terms / credits

- acnh/common.py is based on code provided by Yannik Marchand, used under the MIT License.
See that file for details.
- acnh/design_render.py is provided by @nickwanninger under the AGPLv3 or later license.
- tarfile_stream.py is based on the Python standard library tarfile.py and used under the MIT License.
See that file for details.
