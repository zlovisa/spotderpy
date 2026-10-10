<p align="center">
  <img src="spotderpy/assets/icon.png" width="96" alt="">
</p>

<h1 align="center">Spotderpy</h1>

<p align="center"><b>Copy a Spotify link, get the YouTube video.</b><br>
Songs open straight on YouTube. Playlists and albums become a page of videos with a <i>Play all</i> button.</p>

<p align="center">
  <a href="https://github.com/zlovisa/spotderpy/releases/latest"><b>⬇ Download for Windows</b></a>
</p>

---

## Install

1. Download **`Spotderpy-<version>-Setup.exe`** from the [latest release](https://github.com/zlovisa/spotderpy/releases/latest).
2. Run it. No admin rights needed. It installs just for you.
3. Spotderpy starts and sits in the system tray (bottom-right, maybe under the `^` arrow).

> **"Windows protected your PC"?** Spotderpy is new and not code-signed yet, so SmartScreen doesn't recognize it.
> Click **More info → Run anyway**. The full source code is in this repository and the builds are made by
> [GitHub Actions](.github/workflows/release.yml).

**Portable version:** if you'd rather not install anything, download the `portable.zip`, extract it anywhere, and run `Spotderpy.exe`.

Requires Windows 10 or 11 (64-bit).

## Use it

| Do this | What happens |
|---|---|
| In Spotify, **Share → Copy Song Link** | The YouTube video opens |
| Copy a **playlist** or **album** link | A results page opens with every song's video, a **▶ Play all** button and **Copy all links** |
| Open the Spotderpy window and **paste a link** | See the top matches with thumbnails and pick one |
| Playlist with **more than 100 songs** | Click any song in the playlist in Spotify, press **Ctrl+A** then **Ctrl+C**. Spotderpy gets every song. |

Left-click the tray icon to open the window. Right-click it to pause clipboard watching, reopen recent results, or quit.

### Settings

- **Start when I sign in:** keeps Spotderpy ready in the tray.
- **When I copy a song link:** open the best match right away, or show you the matches first.
- **I prefer:** the official music video, or the audio-only version (the same recording as on Spotify).
- **Notifications**, **clipboard watching**, **where playlist pages are saved** (default `Documents\Spotderpy`), and **automatic update checks**.

## How it picks the video

Spotderpy reads the song's title, artists and length from Spotify's public web page, searches YouTube, and scores the top results:

- **Length**: the strongest signal that it's the same recording, with leeway for music videos that have intros.
- **Official uploads**: the artist's channel, their "Topic" channel, or VEVO.
- **Right version**: if the Spotify title says *Instrumental*, *Live*, *Remix*, *Acoustic*… the video has to as well. Otherwise, covers, live versions, remixes, sped-up and nightcore edits, karaoke and lyric videos are ranked down.

Uncertain matches are highlighted on playlist pages. **Picked the wrong one?** Use *Wrong match?* in the app or [open an issue](https://github.com/zlovisa/spotderpy/issues/new?template=wrong-match.md). Those reports help make the matching better.

## Privacy

Spotderpy has no accounts, no ads and no tracking. It only talks to:
- `open.spotify.com`, to read a song's or playlist's public title and artist info
- `youtube.com` / `i.ytimg.com`, to search and show thumbnails
- `api.github.com`, to check for updates (once a day; you can turn it off)

Your clipboard is only read on your own computer, and only Spotify links are acted on. Settings and history are stored in `%APPDATA%\Spotderpy`. Logs are in `%LOCALAPPDATA%\Spotderpy\logs`.

## FAQ

**It stopped finding videos.** YouTube changes things now and then. Update to the latest version (Settings → About → Check for updates).

**Copying a link does nothing.** Make sure the tray icon is in color, not gray (gray means paused). If you copied the link before Spotderpy started, open the window: the link is pre-filled, so just press **Find**.

**Does it download music?** No. It only finds links and opens them in your browser.

**Uninstall:** Windows Settings → Apps → Installed apps → Spotderpy → Uninstall.

---

<sub>Spotderpy is an independent project and is not affiliated with, endorsed by, or sponsored by Spotify or YouTube.
Licensed under the [MIT License](LICENSE). It bundles [open-source components](spotderpy/assets/THIRD_PARTY_NOTICES.txt).
Developers: see [CONTRIBUTING.md](CONTRIBUTING.md).</sub>
