# Sharp Side

Flags NFL games where at least 70% of tickets are on one side but the line moves the other way (reverse line movement), and tracks how those flags do. Data comes from the Action Network scraper on Apify. A GitHub Action refreshes it every 6 hours, plus two extra runs on Sunday mornings.

## What's in here

| File | What it does |
| --- | --- |
| `index.html` | The phone app |
| `scripts/tracker.py` | Pulls data from Apify, saves it to `data.json`, sends alerts |
| `.github/workflows/tracker.yml` | The schedule that runs the script |
| `manifest.json`, `icon-*.png` | Home-screen name and icon |
| `data.json` | Created automatically on the first run |

## Setup (about 15 minutes, on a computer)

**1. Save your Apify run as a task.** In Apify, open the Action Network scraper with the NFL input you already tested and click **Save as a new task**. Name it something like `nfl-splits`. Your task ID is `your-username~nfl-splits` (it also appears in the task's API tab).

**2. Create the repo.** On GitHub, click **New repository**, name it `nfl-sharp-tracker`, choose **Public**, and check **Add a README** so the repo isn't empty.

**3. Upload the files.** Click **Add file → Upload files** and drag in `index.html`, `manifest.json`, `icon-180.png`, `icon-512.png`, and the `scripts` folder. Commit.

**4. Add the workflow file.** Folders starting with a dot often get skipped on upload, so create this one by hand: **Add file → Create new file**, type `.github/workflows/tracker.yml` as the name, paste in the contents of `tracker.yml`, and commit.

**5. Add your secrets.** Go to **Settings → Secrets and variables → Actions → New repository secret** and add:
- `APIFY_TOKEN`: your Apify API token
- `APIFY_TASK_ID`: the task ID from step 1
- `NTFY_TOPIC` (optional, for push alerts): see below

**6. Turn on Pages.** **Settings → Pages**, source **Deploy from a branch**, branch **main**, folder **/ (root)**, then save. Your app URL appears at the top of that page within a minute or two.

**7. Run it once.** Open the **Actions** tab, choose **Update tracker**, and click **Run workflow**. A green check means `data.json` was created. If it fails, copy the error log and send it to Claude.

**8. Add it to your phone.** Open the app URL. On iPhone, use Safari's **Share → Add to Home Screen**. On Android, use Chrome's menu, then **Add to Home screen**.

## Push alerts (optional)

Install the free **ntfy** app and subscribe to a topic with a long, hard-to-guess name, like `sharpside-ds-7q2k9`. Anyone who knows a topic name can read it, so don't use something obvious. Add that same name as the `NTFY_TOPIC` secret. You'll get an alert the first time any upcoming game is flagged.

## How a flag works

- **Spread:** at least 70% of tickets on one side, and the line moved to give that side a better number (for example, the public is on the Cowboys and the line goes from Cowboys +2.5 to +3). The app shows the other side as the sharp side.
- **Total:** at least 70% of tickets on the over and the total drops, or 70% on the under and it rises.
- **Tags:** "Through a key number" means the move touched or crossed 3 or 7. "Money ahead of tickets" means the sharp side's money % beats its ticket % by 10 or more points.
- **Record:** graded at the closing line. You need about 52.4% to break even at -110.

The slider in the app changes the threshold for what you see. Alerts always use 70% unless you add a `THRESHOLD` secret.

## Costs

GitHub is free for this. Apify bills per row, and this schedule pulls roughly 30 runs × ~16 games a week. Check your Apify usage after the first week, and change the `cron` lines in `tracker.yml` if you want to run less often.

## Limits

- Splits come from Action Network's public data, not the whole market.
- Injury and weather news moves lines too, so check the news before trusting a flag.
- Lines and splits freeze at kickoff. Games already final on the first run are stored with their closing numbers.
