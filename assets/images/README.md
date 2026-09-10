# Images

The icons of the original build are **not redistributed here** — this directory
is intentionally empty apart from this note. Drop your own files in with the
names below if you want the full look.

| file | used for |
|---|---|
| `logo.png` | logo in the navigation rail |
| `logo.ico`, `logo_25.ico`, `test.ico` | window / taskbar icons |
| `home-black.png`, `home-gray.png`, `home-white.png` | Home nav button |
| `settings-black.png`, `settings-gray.png`, `settings-white.png` | Settings nav button |
| `money_bag-black.png`, `money_bag-gray.png`, `money_bag-white.png` | Balance nav button |
| `smile-black.png`, `smile-gray.png`, `smile-white.png` | Commend nav button |
| `green.png`, `red.png` | connection status dots |
| `import.png` | import button |
| `login_selector.png` | template image for the Steam Guard automation |

`AssetLoader` returns `None` for any file that is missing, so every button
falls back to a plain text label and the panel starts normally without a single
image present. The one exception is `login_selector.png`: it is not an icon but
the template the on-screen matching looks for, so without it the Steam Guard
code has to be typed by hand.
