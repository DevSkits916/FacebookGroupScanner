# Facebook Group Scanner

A local Windows Python app that searches Facebook Groups by keyword in an installed browser and exports the visible results to an Excel-friendly CSV file.

The scanner only reads Facebook's Groups search results. It does **not** join groups, post, comment, react, vote, message anyone, or modify your account.

## CSV columns

- `group_name`
- `url`

Duplicate group URLs are removed. CSV files use UTF-8 with a byte-order mark so international group names open correctly in Microsoft Excel.

Facebook does not provide a credential-free public Groups search JSON endpoint. This app therefore uses Playwright with Google Chrome or Microsoft Edge already installed on your computer. No Facebook API credentials are required.

## Windows setup and usage

1. Install Python 3 from <https://www.python.org/downloads/windows/> if needed. Select **Add Python to PATH** during setup.
2. Make sure Google Chrome or Microsoft Edge is installed.
3. Open Command Prompt.
4. Run these exact commands:

```bat
cd %USERPROFILE%\Documents\FacebookGroupScanner\
run.bat
```

5. Choose **1. Search for a keyword**, then enter a keyword and the maximum number of groups (1 to 500 per search).
6. Repeat option **1** for as many different keywords as you need. Each completed search is saved automatically.
7. Choose **2. Export all scanned groups to one CSV** to save every collected group, with duplicate URLs removed. This includes previous searches saved in the exports folder, which are loaded when the app starts.
8. Choose **3. Exit** when finished.
9. On the first run, log in to Facebook normally in the browser window. Return to the terminal and press Enter after login finishes.

The program displays progress and prints the completed CSV's full path. Exports are saved in:

```text
%USERPROFILE%\Documents\FacebookGroupScanner\exports
```

## Login and privacy

The dedicated persistent browser profile is stored locally at:

```text
%USERPROFILE%\Documents\FacebookGroupScanner\browser-profile
```

This allows your Facebook login to remain saved between scanner runs. The app does not request, read, print, or save your password. Facebook itself handles the login in the browser.

Do not share the `browser-profile` folder because it can contain your saved Facebook session. Deleting that folder signs the scanner browser profile out, but also removes its saved browser state.

## How the scan works

The scanner opens Facebook's Groups search page, reads visible group-result cards, scrolls gradually with randomized short delays, and stops when it reaches the requested count or no new groups appear. It detects common login, network, and temporary-rate-limit errors and returns to the menu so earlier collected results can still be exported. The browser closes after each search; the saved profile retains your login for the next search.

Facebook changes its page structure regularly. The scanner only reads each result's group name and URL.

## Optional command-line mode

Running without `--keyword` opens the repeated-search menu. Supplying `--keyword` keeps the single-search workflow and exports that search automatically:

```bat
py -3 facebook_group_scanner.py --keyword gardening --max-results 25
```

## Troubleshooting

- **Python was not found:** install Python 3, enable **Add Python to PATH**, reopen Command Prompt, and run `run.bat` again.
- **Dependency installation failed:** confirm internet access and run `py -3 -m pip --version`.
- **Browser cannot start:** install or update Google Chrome or Microsoft Edge, then close other scanner browser windows and retry.
- **Login still required:** complete any Facebook login checkpoint in the browser before returning to the terminal.
- **Temporarily blocked or limited:** stop and wait before trying again. Do not repeatedly restart the scanner.
- **No groups found after Facebook changes:** Facebook may have changed its page layout; the scanner's read-only selectors may need updating.

## Project files

```text
FacebookGroupScanner\
|-- browser-profile\
|-- exports\
|-- facebook_group_scanner.py
|-- requirements.txt
|-- README.md
`-- run.bat
```
