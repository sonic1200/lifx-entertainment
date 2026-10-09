# LIFX Entertainment

Music-synchronised lighting for [LIFX](https://www.lifx.com/) bulbs and strips, as a
[Music Assistant](https://www.music-assistant.io/) plugin.

It is the LIFX counterpart of Music Assistant's
[Hue Lights Sync](https://www.music-assistant.io/plugins/hue-entertainment/) plugin: each
group of LIFX lights shows up in Music Assistant as a **light player**. Add it to a speaker
group (or play to it directly) and the lights follow the music's beats, energy and the
album-art colours, in sync with the audio.

The repository contains two parts:

| Path | What |
| --- | --- |
| `lifx_entertainment/` | A dependency-free asyncio library for the LIFX LAN protocol: discovery, state snapshot/restore and low-latency colour streaming (including multizone strips). |
| `music_assistant_provider/lifx_entertainment/` | The Music Assistant plugin provider ("LIFX Lights Sync"), modelled on the built-in Hue Entertainment provider. |

## How it works

- Lights are found by **UDP broadcast** on the LAN (port 56700); no cloud account, bridge or
  pairing is needed. Lights that do not answer broadcasts (other VLAN/subnet) can be added by IP.
- Each light player registers in Music Assistant as a Sendspin visualizer client. Music
  Assistant sends it the spectrum, beat grid and album-art palette ahead of playback; the
  plugin renders colours at 20 Hz, timed to the moment the audio is actually heard.
- Colours are sent fire-and-forget (no acknowledgements), duplicate frames are skipped and
  each device is kept under LIFX's recommended 20 messages/second.
- Multizone devices (LIFX Z, Lightstrip, Beam, Neon…) are split into up to 8 segments, so a
  strip shows several colours at once. Lights are spread left to right in the order of
  their names.
- When a session starts, each light's power, colour and zones are saved; lights that were
  off are switched on. When the music stops everything is restored as it was.

### Grouping

| Grouping | Light players |
| --- | --- |
| `group` (default) | One per LIFX group (the rooms of the LIFX app) |
| `all` | A single player with every selected light |
| `light` | One per light |

### Colour modes

`smooth`, `ambient`, `flashing` and `energetic`: the same modes as the Hue plugin.
Brightness, colour mode, power-on behaviour and latency can be changed live from the
plugin settings.

> **Photosensitivity warning:** the `flashing` and `energetic` modes produce fast,
> high-contrast flashes. Do not use them around people who are sensitive to flashing light.

## Installation (Home Assistant OS add-on)

The plugin is not (yet) part of Music Assistant, so it has to be copied into the Music
Assistant container. Tested with Music Assistant **2.10.6**.

1. Install the **Advanced SSH & Web Terminal** add-on and disable its *protection mode*
   (needed for the `docker` command).
2. In its terminal:

   ```sh
   mkdir -p /config/lifx-entertainment
   curl -fsSL -o /config/lifx-entertainment/install_ma_addon.sh \
     https://raw.githubusercontent.com/sonic1200/lifx-entertainment/main/scripts/install_ma_addon.sh
   sh /config/lifx-entertainment/install_ma_addon.sh
   ```

   The script installs the library into Music Assistant's virtualenv, copies the provider
   into `music_assistant/providers/lifx_entertainment`, merges its strings (English and
   French) into Music Assistant's translation files and restarts Music Assistant.
3. In Music Assistant: **Settings → Plugins → Add plugin → LIFX Lights Sync**, then pick the
   lights and the grouping.

**Updates:** the add-on container is re-created whenever Music Assistant is updated (and on
some restarts), which removes the plugin. Either re-run the script, or keep it installed
automatically by adding this to the SSH add-on's `init_commands`:

```yaml
init_commands:
  - nohup sh /config/lifx-entertainment/install_ma_addon.sh watch > /dev/null 2>&1 &
```

`sh install_ma_addon.sh check` tells whether the plugin is currently installed.

## Configuration

| Setting | Default | Description |
| --- | --- | --- |
| Broadcast address | `255.255.255.255` | Use your subnet broadcast (e.g. `192.168.0.255`) if discovery misses lights. |
| Extra hosts | – | Comma-separated IPs of lights that do not answer broadcasts. |
| Brightness | 100 % | Maximum brightness of the effect. |
| Colour mode | `smooth` | See above. |
| Light latency | 100 ms | Delay between sending a colour and the light showing it; raise it if the lights are early. |
| Transition | 50 ms | Fade applied by the bulbs between frames (advanced). |
| Power on lights | on | Switch on lights that are off when a session starts. |

Light IP addresses are refreshed every 10 minutes, so DHCP changes are followed
automatically.

## Limitations

- LIFX bulbs are Wi-Fi devices: under heavy Wi-Fi load some frames may be late or lost.
- Matrix devices (Tile, Candle, Ceiling) are driven as a single colour.
- Lights that are offline when the plugin starts are skipped until the next session.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest tests
ruff check . && mypy lifx_entertainment
```

The tests use a fake LIFX device on localhost; no real lights are needed. When the Music
Assistant server package (`music-assistant @ git+https://github.com/music-assistant/server.git@2.10.6`)
is installed in the same environment, `tests/ma/` also runs the provider against the real
setup flow engine, Sendspin server and visualizer pipeline; otherwise those tests are skipped.

## License

Apache 2.0. The audio analyzer, icons and provider structure come from Music Assistant's
Hue Entertainment provider (Apache 2.0).
