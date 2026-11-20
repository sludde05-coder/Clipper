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
More detail on each key is in [step 6](#6-get-your-api-keys) below. Skipped one? You can add it later in the app's **Settings**.

**4. Open the Clipper app:** double-click **Clipper** on your desktop (the installer puts it there), or
**`Clipper.bat`** in the clipper folder (Mac: **`Clipper.command`**). The app opens in its own window:

| Tab | What you do there |
|---|---|
| **Clipping** | Press **Start clipping**. See which streamers are tracked, how fast their chat is moving, and what the clipper is doing |
| **Clips** | Every streamer's clips. Click one to watch it and **edit its captions**; tick clips and press **Post** |
| **Posting** | Link TikTok, YouTube Shorts and Instagram: turn them on, add your account name and extra hashtags, sign in |
| **Settings** | Your keys (each with a **Test** button) and the main settings |
| **Check** | Tests every part and tells you what to fix |

Clipping keeps running when you close the window. Open Clipper again to get back to it, or press **Quit Clipper**
to stop everything.

**5. Test it today:** on the Clipping tab, choose **Test on another game** (it suggests GTA V) and press
**Start clipping**. Leave it 15–30 minutes, then look in **Clips**. On release day, choose **Top streams** and
press Start. Read [step 9](#9-release-day) for the release-day checklist (keep the computer awake!).

### The AI editing team

Every new clip is edited by five AI editors (five copies of the same model, each with one job):

| Editor | Job | Runs |
|---|---|---|
| **Trim** | Cuts the recording down to where the moment really starts and ends (10–50 s, usually 15–35) | side by side with Webcam |
| **Webcam** | Finds the streamer's webcam in the picture, and where the gameplay action is | side by side with Trim |
| **Captions** | The headline, reaction captions and highlighted words | side by side with Post text |
| **Post text** | The TikTok caption, YouTube title + description and Instagram caption | side by side with Captions |
| **Review** | Looks at the finished video; fixes a weak headline, a wrong webcam crop or captions in the way (one round) | last |

To give the trim editor room, Clipper records 15 s more before and 10 s more after each explosion. The phone clip uses
the **webcam-on-top** layout when the stream has a webcam (setting *Phone clip layout: auto*), and the blurred
background otherwise. Without AI (or with *AI editing team* off in Settings), clips are cut to the usual 22 s before /
8 s after. With Haiku the five editors cost about 0.2 cent per clip, with Opus roughly 10 cents.

### Editing captions

Click a clip in **Clips**:
- **On the video:** change the **headline**, the **colour**, the **layout** (blurred background or full screen), the
  **reaction captions** (pause the video where you want one and press *Add*), and the **spoken words** (to fix
  misheard ones). Then press **Re-render the video** (takes 20–60 seconds).
- **Post captions:** edit the TikTok caption, YouTube title and description, and Instagram caption.
  Press **Save captions**. *Reset to generated* undoes your changes.

To make re-rendering possible, each clip's caption-free original is kept out of sight until the clip is posted
(or deleted). After that, the video's captions can't be changed anymore, but the post captions still can.

### Posting

1. In **Posting**, turn on the platforms you use and click **Sign in to all**. A **normal Chrome window** opens with
   Clipper's own profile called "Clipper". Sign in to TikTok, YouTube and Instagram there ("Continue with Google" works
   in this window), then **close that window**. Clipper uses those logins from then on.
   (Clipper needs its own profile: since version 136, Chrome doesn't let programs control the profiles you make in
   Chrome yourself. And sign-in happens in a normal window because Google blocks signing in from a browser a program
   is controlling.) You need Google Chrome installed.
2. In **Clips**, tick the clips you want to post and press **Post selected**.
3. For each clip and platform, Clipper **puts the video and caption into the upload page** in its browser window.
   On YouTube it also picks "not made for kids", goes through the Next steps and chooses Public.
4. Check it there and click **Post** (TikTok) / **Publish** (YouTube) / **Share** (Instagram), then come back to Clipper
   and press **✓ Posted, next**.
5. Posted clips get a ✓ per platform and move from **To post** to **Posted**.

YouTube titles credit the streamer: `<headline> | <Streamer> #shorts`.

**If a step can't be filled in** (the site changed its page, or wants you to sign in), Clipper says so and you do that
step by hand: the caption is already copied (Ctrl+V) and the clip file is shown in a folder window to drag in.

**Posting completely by itself (optional):** turn on **Also click Post for me** in Posting. Then **Post selected**
asks once, and Clipper does everything for each clip and platform: fills it in, waits for the upload, clicks
Post / Publish / Share, waits for the site to confirm, marks it posted, and moves on. It waits **2 minutes between
clips** (change it under *Minutes between clips*), because a burst of uploads looks like a bot. Press **Close** to
stop. If a site doesn't confirm a post, Clipper stops on that one and asks you to check.
**TikTok, YouTube and Instagram forbid posting with automated browsers.** With this on, the risk of an account
being limited or banned is real, more so than with just filling in. Start with a few clips, and turn it off if a
site starts asking for extra checks.

**About the account risk:** the sites can see that Clipper's window is an automated browser. If one starts asking for
extra checks or blocks uploads, turn off **Fill in the upload page for me** in Posting. Then Post opens the page in your
normal browser, shows the file and copies the caption, and you drag and paste yourself.

### Deleting clips

- **One clip:** open it and press **Delete**.
- **Several at once:** tick them in **Clips** and press **Delete selected** (or the **Delete** key on your keyboard).
- Deleted clips go to **🗑 Deleted clips** at the bottom of the streamer list, so a mistake isn't final:
  tick clips there and press **Restore selected** to bring them back (captions still editable), or
  **Delete forever** / **Empty deleted clips** to free up the disk space for good.

The old text menu still exists as **`Clipper text menu.bat`**, if you ever want it.

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
  📱 saved clips/streamername/Phone clips/streamername_2026-11-17_14-05-33_1.mp4
  ```

Leave it running for **15–30 minutes**. A busy, reactive streamer will usually produce at least one clip.

- **The first phone clip takes a few extra minutes**, because it downloads the speech-to-text model once (~500 MB).
- Press **Ctrl+C** to stop.

**8c. Look at the result.** Open the `clipper/clips` folder:
- **Windows:** `explorer clips`
- **Mac:** `open clips`

Play the clip in the streamer's `Phone clips` folder. Check that it starts before the moment that set chat off, and that the captions look right.

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

Everything goes into the `clips` folder, with a folder per streamer:

```
clips/
  KaiCenat/
    Phone clips/
      KaiCenat_2026-11-19_21-34-12_1.mp4
      KaiCenat_2026-11-19_22-05-40_2.mp4
    Captions and details/
      KaiCenat_2026-11-19_21-34-12_1.json
      KaiCenat_2026-11-19_22-05-40_2.json
  xQc/
    ...
```

| Folder | What's in it |
|---|---|
| `Phone clips` | **The clips to post:** 30 s (22 s before chat explodes, 8 s after), 1080×1920, with captions |
| `Captions and details` | One `.json` per clip: the caption plan, **`post_caption`** (a ready-made caption with hashtags), chat speed, what chat said and the transcript |

Names are **streamer, date, time, clip number**: `KaiCenat_2026-11-19_21-34-12_3` is KaiCenat's 3rd clip, from when chat
exploded at 21:34:12 on 19 November. The number keeps counting across days and restarts. `clips/index.jsonl` lists
every clip in order.

The 16:9 original is **deleted once the phone clip is made**. These folders can also appear:
- **`Not converted`**: the phone version couldn't be made, so the original is kept here.
- **`Other languages`**: the streamer clearly spoke another language. These get no phone version.
- **`Originals`**: only if you set `keep_originals = true` under `[clips]` in `config.toml`.
- **`.work`**: clips being processed right now. Leave it alone.

The `buffer` folder is temporary video the app deletes as it goes. You can ignore it.

---

### The phone app

With the Clipper app open on your PC, the phone app does nearly everything the PC app does:
- **🎬 Clips:** swipe through your clips like TikTok (small preview versions, so it's smooth on Wi-Fi or mobile
  data). On each clip: **Post** (Clipper's caption per platform, Save/Share video, Mark as posted), **Edit**
  (headline, layout, colour, spoken captions, then re-render on the PC), **🏆** (pick it for a Top 10),
  **Delete** (to Deleted clips on the PC) and **Sound**.
- **🎥 Clipping:** start and stop clipping, set the top N and your own streamers (links), see the streams being
  clipped with their chat speed, block a streamer, and the activity log.
- **🏆 Top 10:** today's Top 10 or Top 5, or one from your picks: pick the part of each moment in one player,
  change the order, split into 2 parts, music and whoosh, with a progress bar while the PC makes it.
- **⚙️ Settings:** everything except keys and passwords (those stay on the PC).

**Connect your phone (once):**
1. On your PC, in Clipper, go to **Posting**: the **📱 Phone app** card has a **QR code**.
2. **Windows asks whether Python may use networks:** tick **Private networks** and click **Allow**.
   Without this, the phone can't connect.
3. Open the phone's **camera**, point it at the QR code, and tap the link. (At home on the same Wi-Fi, or anywhere
   with Tailscale, see below.)
4. Add it to your home screen so it opens like an app:
   - **iPhone** (Safari): tap Share **⬆︎** → **Add to Home Screen** → Add.
   - **Android** (Chrome): tap **⋮** → **Add to Home screen** (or **Install app**).

**"Share" or "Save video"?** Phones only allow sharing a video straight into another app from a secure (https)
connection. At home over Wi-Fi the app uses plain http, so you'll usually see **Save video**:
- **Android:** the video goes to Downloads. In TikTok, Instagram or YouTube, tap + and pick it.
- **iPhone:** the video goes to the **Files** app. Open it there, tap Share → **Save Video** (now it's in Photos),
  then pick it in TikTok, Instagram or YouTube.

For one-tap **Share** buttons, and to post when you're away from home, see "Posting from anywhere" below.

**Posting from anywhere (not just your home Wi-Fi):** use the free app **Tailscale**. It connects your own devices
to each other privately, so the phone reaches Clipper on mobile data or any Wi-Fi, without opening it to the internet.
1. Install Tailscale on the PC and the phone ([tailscale.com/download](https://tailscale.com/download)) and sign in
   with the same account on both.
2. Restart Clipper. In **Posting → 📱 Phone app** it now says **Works from anywhere**: scan that QR code and add the
   page to your home screen again.
3. Keep the Tailscale app switched on, on your phone. (At home it works too.)

If the phone can't connect through Tailscale, Windows Firewall may be blocking it: when Windows asks whether Python
may use networks, allow both **Private** and **Public**.

**One-tap Share buttons (optional, with Tailscale):** phones only allow sharing straight into another app from an
https address.
1. In the Tailscale admin page (login.tailscale.com → **DNS**), turn on **HTTPS Certificates**.
2. On the PC, open a terminal and run: `tailscale serve --bg 8765`. It prints an address like
   `https://your-pc.tail1234.ts.net`.
3. Put that address in `config.toml` under `[phone]`: `public_url = "https://your-pc.tail1234.ts.net"`, restart
   Clipper and scan the new QR code.

### Posting your clips on the PC

1. Open the clipper menu and choose **7**. A `POST` folder opens (it's inside your clipper folder).
2. Copy a clip you like into it, from a streamer's **`Phone clips`** folder. Leave that window open.
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
| Too many clips / boring clips | Raise *How big a chat explosion must be* (`multiplier`) or *Minimum rise in chat speed* (`min_jump`), or raise `cooldown` |
| Missing big moments | Lower `multiplier` to `2.5`. Busy chats already need a smaller jump than quiet ones (about x2.4 at 6 msg/s, x1.7 at 15) |
| Clips start too late (the moment is cut off) | Raise `pre_roll` (e.g. `25`) and lower `post_roll` to keep 30 s, or raise `chat_delay` (e.g. `3`) |
| Clips end too early | Raise `post_roll` (the clip gets longer than 30 s), or lower `pre_roll` to keep 30 s |
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
| Installer: `Couldn't install` speech-to-text, "conflicting dependencies" | Usually a Windows ARM PC (Snapdragon / Surface Pro 11 / Copilot+). Get the latest clipper and run `install.bat` again: it switches to x64 Python, which Windows runs through emulation |
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
