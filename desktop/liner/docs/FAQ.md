# FAQ and known issues

Answers to the questions that come up most. If yours isn't here, open an
[issue](https://github.com/tryliner/desktop/issues/new/choose) or ask in
[Discussions](https://github.com/tryliner/desktop/discussions).

## Tracks don't play ("Track unavailable", "track failed")

Liner plays music from your device straight from YouTube Music, so it stops working when
YouTube is blocked or throttled on your network or in your region.

1. Open <https://music.youtube.com> in a normal browser on the same computer and network
   and play a song there.
2. If that doesn't work either, the problem is your connection: turn on a VPN, or sign in
   to your YouTube account in **Settings → YouTube**, and try again.
3. If YouTube Music works in the browser but Liner doesn't on the latest version, open a
   bug report with your Liner version and the error.

## Playlist import fails

Imports read the playlist from the source (Spotify, Apple Music, Deezer, SoundCloud,
YouTube) and match every track on YouTube Music from your device. Make sure both the
source site and <https://music.youtube.com> open in your browser, use a VPN if they don't,
and check that the playlist is public.

## macOS says Liner is damaged or can't be opened

The macOS builds aren't signed. Move Liner to Applications, then run this once in
Terminal:

```
xattr -dr com.apple.quarantine /Applications/Liner.app
```

Right-click → **Open** on the app works as well. Updates on macOS are installed by
downloading the new release.

## I can't register ("429")

Registration is limited to one account per IP address, so a 429 means an account was
already created from your network. Sign in with that account.

## Where does Liner keep my data, and what does it send?

See [STORAGE.md](./STORAGE.md) and [PRIVACY.md](./PRIVACY.md).
