# Windows installation and production validation

Validated on 27 October 2026 using an isolated clone of the public repository on
an existing Windows laptop, with Python 3.12.15 and Node.js 22.14.0. This was not a
fresh Windows virtual machine. The application environments were newly created;
no existing account credentials, application environments, narration cache or
background collection were copied into the test workspace. Package download
caches could be reused by the installers.

## Passed

- Ran `setup.cmd` with an explicit Python 3.12 executable path. Both Python
  environments installed successfully; `pip check` reported no conflicts.
- Installed dashboard packages from the lockfile and completed the production build.
- Passed all 25 offline Python tests, including the release API-route regression test.
- Started the built dashboard in a browser and checked its video queue.
- Added an unconnected channel profile, switched profiles and saved settings.
- Downloaded the narration model and English language resources on first use.
- Generated a real 39.4-second video from a bundled story through the command line.
- Generated a second 44.55-second video using the dashboard's Create videos button.
- Used a temporary generated vertical background, rather than a bundled media asset.
- Decoded both completed videos fully with FFmpeg and inspected a rendered caption frame.
- Previewed an upload using `--dry-run`; no video was uploaded.
- Checked disabled startup uploading and the daily scheduler's one-shot dry run.
- Confirmed scheduling remained disabled and no OAuth credential files were created.
- Verified the upload button was disabled without a connected account and that
  Connect channel explained where to supply the missing OAuth client JSON.

## Fixes found during validation

The original release ignored every directory named `channels`, which also hid
`dashboard/app/api/channels/route.js` from Git. The ignore rule now applies only
to the root local-data directory, and the dashboard endpoint is distributed.

The setup script now accepts a Python executable path for installations that the
Windows launcher does not resolve through `py -3.12`.

## Not validated live

- A new user's Google OAuth sign-in, real YouTube upload or analytics retrieval.
- Publishing at an actual scheduled time or on a real Windows sign-in.
- Live Reddit collection or the standalone viewer script.
- Other Windows machines, hardware configurations, antivirus products or future
  dependency releases.

This validation supports the local setup and video-production flow on the tested
machine. It does not guarantee that every external service or environment works.
