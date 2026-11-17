# Setup guide, step by step

## ⚡ Easy install (recommended)

An installer does nearly everything for you: it installs Python, ffmpeg and the clipper, tests that it works,
downloads the speech model, and walks you through your API keys.

**1. Download the project.** On [github.com/sludde05-coder/clipper](https://github.com/sludde05-coder/clipper)
click the green **Code** button → **Download ZIP**. Then unzip it:
- **Windows:** right-click the ZIP → **Extract All** → **Extract**.
- **Mac:** double-click the ZIP.

Move the unzipped `clipper` folder somewhere you'll find it, e.g. **Documents**.

**2. Run the installer** in that folder:

| Windows | Mac |
|---|---|
| Double-click **`install.bat`** | Right-click **`install.command`** → **Open** → **Open** |
| If a blue "Windows protected your PC" box appears: **More info** → **Run anyway** | The right-click is needed the first time, because the file came from the internet |
| Click **Yes** if Windows asks for permission while it installs | Type your Mac password if asked (nothing shows while typing; that's normal) |

It takes **5–15 minutes**. Each part shows `[OK]` (or ✔) as it finishes.

**3. Enter your API keys when it asks.** For each service, it opens the right web page in your browser and lists
what to click. You copy the key, paste it into the installer window, and it **checks the key works** before saving.
Paste with **Ctrl+V** or right-click (Windows) or **Cmd+V** (Mac). You need at least **Twitch**.
More detail on each key is in [step 6](#6-get-your-api-keys) below. Skipped one? You can add it later from the menu.

**4. Start the clipper:** double-click **`Clipper.bat`** (Windows) or **`Clipper.command`** (Mac). A menu opens:

```
  1) Start clipping: the top 10 GTA 6 streams
  2) Show who's in the top 10 right now
  3) Clip specific streamers
  4) Test on a game that's live right now
  5) Open the clips folder
  6) Set up or change API keys
  7) Post clips on this PC (drop them in the POST folder)
  8) Phone app: post clips from your phone
  9) Check that everything works
 10) Quit
```

Type a number and press Enter. **Ctrl+C** stops clipping and takes you back to the menu.

**5. Test it today:** choose **4** and press Enter to use GTA V. Leave it running 15–30 minutes, then choose
**5** to see your clips. On release day, choose **1**. Read [step 9](#9-release-day) for the
release-day checklist (keep the computer awake!).

> **Installer failed?** It says which part failed and why. Fix that and run it again. It's safe to re-run,
> and it skips whatever is already done. Or follow the manual steps below.

---

# Manual setup

Use this if the installer didn't work, or if you'd like to do it yourself.

This takes you from nothing installed to clips saving automatically. Follow the steps in order.
Each step says what you should see when it worked, so you know it's safe to move on.

**Time needed:** about 30–45 minutes, most of it creating the free API keys.

**Contents**

1. [What you need](#1-what-you-need)
2. [Open a terminal](#2-open-a-terminal)
3. [Install Python, ffmpeg and Git](#3-install-python-ffmpeg-and-git)
4. [Download the project](#4-download-the-project)
5. [Install the project's parts](#5-install-the-projects-parts)
6. [Get your API keys](#6-get-your-api-keys)
7. [Fill in the config file](#7-fill-in-the-config-file)
8. [Test that everything works](#8-test-that-everything-works)
9. [Release day](#9-release-day)
10. [Your clips (and posting them)](#10-your-clips-and-posting-them)
11. [Adjusting how it clips](#11-adjusting-how-it-clips)
12. [Troubleshooting](#12-troubleshooting)
13. [Updating to a newer version](#13-updating-to-a-newer-version)
14. [Cheat sheet](#14-cheat-sheet)

---

## 1. What you need

- **A Windows 10/11 PC or a Mac.** It runs on your own computer and records while the computer is on.
- **Fast internet.** Recording 10 streams at once needs about **60–80 Mbit/s download**.
  Check your speed at [fast.com](https://fast.com). If it's lower, you'll use `720p` quality (step 11).
- **Free disk space:** about 5 GB to start (the speech model is ~500 MB, each clip 10–40 MB).
- **A Twitch account with two-factor login turned on.** Twitch requires this before it gives you a key.
  To turn it on: twitch.tv → your avatar → **Settings → Security and Privacy → Enable Two-Factor Authentication**.
- **Optional:** an Anthropic account with a few dollars of credit, for the AI-written captions.
  Without it, clips still get captions based on chat.

---

## 2. Open a terminal

Almost every step types a command into a **terminal**: a window where you type commands and press **Enter**.

**Windows:** press the **Windows key**, type `PowerShell`, and click **Windows PowerShell**.
A blue or black window opens with a line like `PS C:\Users\YourName>`.

**Mac:** press **Cmd + Space**, type `Terminal`, and press **Enter**.
A window opens with a line ending in `%`.

> **Tips**
> - Paste into the terminal with **Ctrl+V** (Windows) or **Cmd+V** (Mac). In older PowerShell windows, right-click pastes.
> - Type or paste **one command at a time**, then press Enter and wait until the line with `>` or `%` comes back.
> - **Ctrl+C** stops whatever is running.
> - In this guide, only the text inside the grey boxes is a command. Don't type the `#` comments; they're just notes.

---

## 3. Install Python, ffmpeg and Git

You only do this once.

### Windows

**3a. Python**

1. Go to [the Python 3.12 download page](https://www.python.org/downloads/release/python-31210/), scroll down to **Files**, and click **Windows installer (64-bit)**.
   ⚠️ Use **3.12** (3.11 and 3.13 also work). Newer versions like 3.14 and 3.15 are too new for the speech-to-text part.
   You can keep a newer Python installed too; they don't interfere.
2. Run the downloaded file.
3. ⚠️ **On the first screen, tick "Add python.exe to PATH"** at the bottom. This is the most common mistake.
   If you miss it, run the installer again, choose **Modify**, and tick it.
4. Click **Install Now** and wait for "Setup was successful".

**3b. ffmpeg and Git.** In PowerShell, run these one at a time. Answer `Y` if asked to agree to terms.

```powershell
winget install ffmpeg
```
```powershell
winget install Git.Git
```

**3c. Close PowerShell completely and open a new one.** New programs only show up in new terminal windows.

**3d. Check everything is installed:**

```powershell
python --version
ffmpeg -version
git --version
```

✅ You should see `Python 3.12` (3.11 or 3.13 are fine too), a block of text starting with `ffmpeg version`, and `git version ...`.

> If `python --version` shows a newer version (3.14, 3.15…), that's fine as long as you installed 3.12 as well.
> In step 5a you'll use `py -3.12` to pick it.

❌ If `python` opens the Microsoft Store or says "not found", Python isn't on PATH. Redo 3a, step 3.
You can also try `py --version`; if that works, type `py` wherever this guide says `python`.

### Mac

**3a. Homebrew** (an installer for developer tools). Paste this into Terminal:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

- It asks for your Mac password. Nothing appears while you type it; that's normal. Press Enter.
- When it finishes, it shows **"Next steps"** with two or three commands starting with `echo` and `eval`.
  **Copy and run those too**, or `brew` won't be found.

**3b. Python, ffmpeg and Git:**

```bash
brew install python@3.12 ffmpeg git
```

**3c. Check everything is installed:**

```bash
python3.12 --version
ffmpeg -version
git --version
```

✅ You should see `Python 3.12...`, `ffmpeg version ...` and `git version ...`.

> **Mac users:** use `python3` everywhere this guide says `python`.

---

## 4. Download the project

Choose where the project goes. The commands below put it in your user folder.

```bash
cd ~
git clone https://github.com/sludde05-coder/clipper
cd clipper
```

✅ You now have a `clipper` folder, and your terminal is "inside" it: the prompt line ends in `clipper>` or `clipper %`.

> **If the repo is private**, Git asks you to sign in to GitHub. A browser window opens. Log in and approve, and the download continues.

---

## 5. Install the project's parts

**5a. Create a "virtual environment".** This is a private Python just for this project, so it doesn't mess with anything else on your computer.

Windows:
```powershell
py -3.12 -m venv .venv
```
Mac:
```bash
python3.12 -m venv .venv
```

**5b. Activate it.** You must do this **every time you open a new terminal** to use the clipper.

Windows:
```powershell
.venv\Scripts\activate
```

Mac:
```bash
source .venv/bin/activate
```

✅ The prompt line now starts with `(.venv)`.

❌ **Windows: "running scripts is disabled on this system"?** Run this once, answer `Y`, then try activating again:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**5c. Install the parts:**

```bash
pip install -r requirements.txt
pip install -r requirements-speech.txt
```

This downloads a lot of text and can take a few minutes. The second line adds speech-to-text for
word-by-word captions. If only that line fails, the clipper still works, just without word-by-word captions.

✅ It ends with a line starting with `Successfully installed ...`.

**5d. Quick check that it runs:**

```bash
python -m clipper -c none simulate
```

✅ You should see three lines with 🔥, the detector catching three fake chat explosions:

```
  🔥 fired at   241s  onset   240s    24.0 msg/s vs  7.6 normal  →  clip 210s..261s
  🔥 fired at   423s  onset   420s    30.6 msg/s vs  8.0 normal  →  clip 390s..443s
  🔥 fired at   601s  onset   600s    33.8 msg/s vs  8.4 normal  →  clip 570s..621s
```

---

## 6. Get your API keys

The keys only let the app **find** the biggest streams. Reading chat and recording need no keys.
You need **at least one** platform. Start with **Twitch**, since most big GTA streams will be there.

Open a text file (Notepad or TextEdit) and paste each key into it as you get it. You'll copy them into the config in step 7.

> 🔒 Treat these keys like passwords. Don't post them or share screenshots of them.

### 6a. Twitch (most important)

1. Make sure two-factor login is on for your Twitch account (see step 1).
2. Go to [dev.twitch.tv/console](https://dev.twitch.tv/console) and log in with Twitch.
3. Click **Applications** → **Register Your Application**.
4. Fill in:
   - **Name:** anything unique, e.g. `yourname-clipper` (it must not be taken).
   - **OAuth Redirect URLs:** `http://localhost`, then click **Add**.
   - **Category:** `Other`.
   - **Client Type:** **Confidential**.
5. Tick the captcha and click **Create**.
6. Next to your new app, click **Manage**.
7. Copy the **Client ID** and save it as "Twitch client ID".
8. Click **New Secret**, confirm, and copy the long code that appears. Save it as "Twitch client secret".
   ⚠️ It is only shown once. If you lose it, click **New Secret** again.

### 6b. YouTube

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and sign in with a Google account.
   Accept the terms if asked. No payment card is needed.
2. At the top left, click the project dropdown (it may say **Select a project**) → **New Project**.
   Name it `clipper` and click **Create**. Wait a few seconds, then select that project in the dropdown.
3. In the search bar at the top, type `YouTube Data API v3`, click it, and click **Enable**.
4. In the left menu, go to **APIs & Services → Credentials**.
5. Click **+ Create credentials → API key**.
6. Copy the key (it starts with `AIza`) and save it as "YouTube key".

> YouTube gives 10,000 free "quota units" a day. Each search costs 100, so the app only searches
> every 15 minutes. That way it never runs out.

### 6c. Kick

1. Log in at [kick.com](https://kick.com). Two-factor login may need to be on (Kick settings → **Security**).
2. Go to [kick.com/settings/developer](https://kick.com/settings/developer).
3. Click **Create App** (or similar). Give it a name, use `http://localhost` as the redirect URL, and tick the read/public permissions.
4. Copy the **Client ID** and **Client Secret** and save them as "Kick ID" and "Kick secret".

> If Kick's developer page looks different or isn't available on your account, skip Kick.
> Twitch and YouTube are enough. You can still track specific Kick streamers by hand (step 11).

### 6d. Anthropic (optional, for AI captions)

1. Go to [console.anthropic.com](https://console.anthropic.com) and sign up.
2. Go to **Billing** and add credit. $5 covers well over a hundred clips.
3. Go to **API Keys → Create Key**, name it `clipper`, and copy the key (starts with `sk-ant-`).
   ⚠️ It is only shown once.

---

## 7. Fill in the config file

**7a. Make your own copy of the example config:**

Windows:
```powershell
copy config.example.toml config.toml
```
Mac:
```bash
cp config.example.toml config.toml
```

**7b. Open it in a text editor:**

Windows:
```powershell
notepad config.toml
```
Mac:
```bash
open -e config.toml
```

> **Shortcut:** instead of editing the file by hand, run `python -m clipper setup`. It asks for each key,
> checks it, and saves it for you.

**7c. Paste your keys between the quotes.** Scroll to the bottom. Fill in the sections for the keys you have and leave the rest as `""`.
It should look like this, with your own keys:

```toml
[twitch]
client_id = "abc123yourclientid"
client_secret = "xyz789yoursecret"

[youtube]
api_key = "AIzaSyYourKeyHere"

[kick]
client_id = ""
client_secret = ""
category_id = 0

[anthropic]
api_key = "sk-ant-yourkeyhere"
```

⚠️ Keep the quotes `" "` around each key, and don't add spaces inside them.

**7d. Save and close** (Ctrl+S / Cmd+S).

Leave the rest of the file as it is for now. Step 11 explains the other settings.

---

## 8. Test that everything works

GTA 6 isn't out yet, so test on a game that's live **right now**. This catches problems before release day.

> Remember: in a new terminal, first go into the folder and activate (step 5b):
> `cd ~/clipper`, then `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Mac).

**8a. Are the keys working?**

```bash
python -m clipper discover --game "Grand Theft Auto V"
```

✅ You see a numbered list of the biggest GTA V streams:
```
 1. twitch   summit1g                     24,512  NoPixel...
 2. youtube  SomeStreamer                  9,870  GTA RP live...
 ...
```

❌ `Twitch credentials missing` means the keys aren't in `config.toml`, or you're not in the `clipper` folder.
❌ `401` or `invalid client` means a key was copied wrong. Copy it again (a new secret for Twitch).

**8b. Record one stream for real.** Pick a big streamer who is live right now and has a busy chat.
Use their name from their twitch.tv URL:

```bash
python -m clipper watch twitch:STREAMERNAME
```

(For Kick: `kick:streamername`. For YouTube, paste the full live video link.)

✅ Within about 10 seconds you'll see:
```
14:02:11 INFO    twitch:streamername chat connected
14:02:12 INFO    twitch:streamername recording started
```
and every 30 seconds a status table:
```
channel                          video   chat/s  normal clips
twitch:streamername              live      12.4    11.8     0
```

- `chat/s` is how fast chat is moving now, and `normal` is how fast it usually moves.
- The first minute is warm-up, while it learns what "normal" is for this chat.
- When chat explodes to several times its normal speed, you'll see:
  ```
  🔥 twitch:streamername chat exploded: 58.2 msg/s vs 11.8 normal (x4.9, z=12.1)
  🎬 saved clips/twitch_streamername_20261117-140533.mp4
  ✍️  ... "Streamer just went CRAZY" (hype, claude, 61 words, 2 beats)
  📱 saved clips/twitch_streamername_20261117-140533_vertical.mp4
  ```

Leave it running for **15–30 minutes**. A busy, reactive streamer will usually produce at least one clip.

- **The first phone clip takes a few extra minutes**, because it downloads the speech-to-text model once (~500 MB).
- Press **Ctrl+C** to stop.

**8c. Look at the result.** Open the `clipper/clips` folder:
- **Windows:** `explorer clips`
- **Mac:** `open clips`

Play the `_vertical.mp4` clip. Check that it starts before the moment that set chat off, and that the captions look right.

✅ If you got a clip, **you're ready for release day.**

---

## 9. Release day

**9a. Before you start:**
- **Keep the computer awake.**
  - Windows: **Settings → System → Power** → set **Sleep** to **Never** while plugged in.
  - Mac: **System Settings → Battery/Energy** → turn on **Prevent automatic sleeping when the display is off**.
    Or, in a second terminal window, run `caffeinate -d` (Ctrl+C to undo).
- **Plug in a laptop** and close downloads or games that use your internet.

**9b. Check the GTA 6 category exists** (step 5b first, as always):

```bash
python -m clipper discover
```

✅ A list of GTA 6 streams appears.

❌ "Nothing live" while GTA 6 streams clearly are live? Twitch probably named the category differently.
Open a GTA 6 stream on twitch.tv, click the game name under the title, and copy the exact name.
Put it in `config.toml` after `game =`, e.g. `game = "Grand Theft Auto VI"`, then try again.

**9c. Start clipping:**

```bash
python -m clipper run
```

It finds the 10 biggest GTA 6 streams across all platforms and records them all. Every 5 minutes it re-checks,
starting new streams that climb into the top 10 and dropping ones that fall out. Leave the window open; it runs until you press Ctrl+C.

> Want specific streamers recorded no matter what? Add them in `config.toml`:
> `always_track = ["twitch:kaicenat", "kick:adinross"]`

---

## 10. Your clips (and posting them)

Everything goes into the `clips` folder. Each clip has three files:

| File | What it is |
|---|---|
| `twitch_name_20261119-131434.mp4` | The original 16:9 clip: 30 s before the chat explosion and 20 s after |
| `twitch_name_20261119-131434_vertical.mp4` | **The phone version** (1080×1920) with captions. Post this one |
| `twitch_name_20261119-131434.json` | Details: chat speed, what chat said, the transcript, and **`post_caption`**, a ready-made caption with hashtags to copy |

The name is `platform_streamer_date-time` (time of the explosion). `clips/index.jsonl` lists every clip in order.

Want the phone version in the other layout (full-screen crop instead of a blurred background)?

```bash
python -m clipper render clips/twitch_name_20261119-131434.mp4 --layout crop
```

**`clips/other-languages`** holds clips where the streamer clearly speaks another language, in case one
slipped past the English-only filter. They get no phone version. Delete them or keep them, as you like.

The `buffer` folder is temporary video the app deletes as it goes. You can ignore it.

---

### Posting from your phone (the phone app)

The phone app shows the clips in your `POST` folder on your phone. You post them from the phone, and they move
to `POST/posted` on your PC when you're done.

**Connect your phone (once):**
1. On your PC, open the clipper menu and choose **8) Phone app**. A page with a **QR code** opens.
2. **Windows asks whether Python may use networks:** tick **Private networks** and click **Allow**.
   Without this, the phone can't connect.
3. Make sure your phone is on the **same Wi-Fi** as your PC. Open the phone's **camera**, point it at the
   QR code, and tap the link.
4. Add it to your home screen so it opens like an app:
   - **iPhone** (Safari): tap Share **⬆︎** → **Add to Home Screen** → Add.
   - **Android** (Chrome): tap **⋮** → **Add to Home screen** (or **Install app**).

**Posting a clip:**
1. On the PC, copy a clip (the `_vertical.mp4` one) into the `POST` folder. The app shows it within a few seconds.
   The app works whenever the clipper is clipping (options 1, 3, 4) or while option 8 is open.
2. In the app, tap the clip. For each platform you get:
   - **Share to TikTok/Instagram/YouTube** (or **Save video**, see below): puts the video into the app.
   - **Copy caption** (YouTube: **Copy title** and **Copy description**), written for that platform.
     Sharing copies the caption automatically, so you just paste it.
   - **Mark as posted** once it's up.
3. Tap **Done: move to Posted**. The clip moves to `POST/posted` on your PC, and the log notes where it went.

**"Share" or "Save video"?** Phones only allow sharing a video straight into another app from a secure (https)
connection. At home over Wi-Fi the app uses plain http, so you'll usually see **Save video**:
- **Android:** the video goes to Downloads. In TikTok, Instagram or YouTube, tap + and pick it.
- **iPhone:** the video goes to the **Files** app. Open it there, tap Share → **Save Video** (now it's in Photos),
  then pick it in TikTok, Instagram or YouTube.

For one-tap **Share** buttons, and to post when you're away from home, see "Posting from anywhere" below.

**Posting from anywhere (optional):** with the free app **Tailscale** on your PC and phone, the phone app gets a
secure https address that works on mobile data too, and the one-tap Share buttons appear.
1. Install Tailscale on the PC and the phone ([tailscale.com/download](https://tailscale.com/download)) and log in
   with the same account on both.
2. In the Tailscale admin page (login.tailscale.com → **DNS**), turn on **HTTPS Certificates**.
3. On the PC, open a terminal and run: `tailscale serve --bg 8765`. It prints an address like
   `https://your-pc.tail1234.ts.net`.
4. Put that address in `config.toml` under `[phone]`: `public_url = "https://your-pc.tail1234.ts.net"`.
5. Choose **8) Phone app** again and scan the new QR code (add it to your home screen again too).

### Posting your clips on the PC

1. Open the clipper menu and choose **7**. A `POST` folder opens (it's inside your clipper folder).
2. Copy a clip you like into it: the **`_vertical.mp4`** one from `clips`. Leave that window open.
3. The clipper picks it up within a few seconds and goes through **TikTok, YouTube Shorts and Instagram Reels** one at a time:
   - It opens the platform's upload page in your browser, and a folder window with the clip selected.
   - **Drag the clip** from the folder window onto the upload page.
   - The caption is **already copied** for that platform: paste it with **Ctrl+V** (Cmd+V on a Mac).
     It has the AI-written line, credit to the streamer (e.g. "🎥 KaiCenat on Twitch") and hashtags.
     YouTube gets a title and a description, copied one after the other.
   - Press **Post**, then go back to the clipper window and press **Enter** for the next platform.
     Type **s** and Enter to skip a platform.
4. When it's done, the clip moves to `POST/posted`, with a `.txt` file next to it holding every caption.
   That's handy if you'd rather post from your phone.

You need to be logged in to TikTok, YouTube and Instagram in your browser. Drop several clips in at once
and it takes them one after another. To change the platforms or turn off the streamer credit, edit `[post]`
in `config.toml`, e.g. `platforms = ["tiktok", "youtube"]`.

> Why not fully automatic? TikTok and YouTube keep videos uploaded by unapproved apps private, Instagram needs
> a business account and a Meta developer app, and bots that click through the websites get accounts banned.
> This way you just press Post, and nothing can get your account in trouble.

## 11. Adjusting how it clips

All settings are in `config.toml`. Open it, change a value, save, then stop (Ctrl+C) and restart the app.

| Problem | Setting to change |
|---|---|
| Too many clips / boring clips | Raise `multiplier` from `3.0` to `4.0`, or raise `cooldown` |
| Missing big moments | Lower `multiplier` to `2.5` |
| Clips start too late (the moment is cut off) | Raise `pre_roll` (e.g. `45`) or `chat_delay` (e.g. `5`) |
| Clips end too early | Raise `post_roll` |
| Internet can't keep up / video stutters | Set `quality = "720p"`, or lower `top_n` to `5` |
| Computer is slow / fans loud | Set `whisper_model = "base"` (faster, slightly worse captions) |
| Want full-screen phone clips | Set `layout = "crop"` |
| Small streamers getting in the top 10 | Raise `min_viewers` |
| Want other languages too | `languages = ["en", "es"]` adds Spanish; `languages = []` allows every language |

---

## 12. Troubleshooting

**Start with the check:** open the clipper menu and choose **9) Check that everything works**. It tests
Python, ffmpeg, the video downloader, speech-to-text (and offers to download its model), your AI key and your
stream keys. It also tells you whether your last few clips actually got AI captions and speech-to-text.
Every ✘ line comes with what to do about it.


| What you see | What to do |
|---|---|
| `python` not found (Windows) | Reinstall Python and tick **Add python.exe to PATH**, or use `py` instead |
| `No module named clipper` | You're not in the `clipper` folder: `cd ~/clipper` |
| `No module named aiohttp` (or similar) | You forgot to activate: step 5b |
| `ffmpeg` not found | Close the terminal and open a new one. If still missing, redo step 3 |
| `discover` says credentials missing | Check `config.toml` (not `config.example.toml`) has your keys, inside quotes |
| `discover` shows nothing | No one is live in that game, or the category name is different (step 9b) |
| Chat connects but `video` stays `--` | The streamer is offline, or the video download is blocked. Run `pip install -U streamlink` |
| `kick ... chat dropped (403)` | Kick blocked the chat-room lookup. See the Kick note in README.md |
| `youtube chat unavailable` for one stream | That stream has chat turned off, or has ended. Others keep working |
| `youtube chat unavailable` for every YouTube stream | YouTube changed its chat page. Get the latest version (step 13) or ask for a fix |
| `using rule-based captions` | Not an error: no Anthropic key or credit, so captions are based on chat. Check `[anthropic]` in config and your credit balance |
| `transcription failed` | The speech model couldn't download. Check your internet and disk space, then restart |
| Phone clip has no word-by-word captions | Nobody spoke, or transcription failed (see above) |
| Clips folder stays empty | Chat didn't explode enough. Wait longer, pick a busier stream, or lower `multiplier` |

Still stuck? Copy the whole error message from the terminal and send it to whoever helps you (or to Claude).

---

## 13. Updating to a newer version

**Downloaded the ZIP?** Download the new ZIP and unzip it. Copy your `config.toml` and `clips` folder from
the old folder into the new one, then double-click the installer in the new folder. It keeps your keys.

**Used `git clone`?**

When the code on GitHub changes:

```bash
cd ~/clipper
git pull
```
Then activate (step 5b) and run:
```bash
pip install -r requirements.txt
pip install -r requirements-speech.txt
```

Your `config.toml` and `clips` are never touched by updates.

---

## 14. Cheat sheet

**Installed with the installer?** Just double-click `Clipper.bat` (Windows) or `Clipper.command` (Mac).

Or from a terminal, every time you want to use it:

```bash
cd ~/clipper
.venv\Scripts\activate             # Windows
source .venv/bin/activate          # Mac

python -m clipper                  # the menu
python -m clipper setup            # enter or change API keys
python -m clipper discover         # who's live in the top 10?
python -m clipper run              # record and clip the top 10
python -m clipper watch twitch:NAME kick:NAME   # record specific streamers
python -m clipper render clips/FILE.mp4 --layout crop   # redo a phone clip
```

Ctrl+C stops it. Clips are in `clipper/clips`.
