# Runs once a day via Windows Task Scheduler (see scripts/register_scheduled_task.ps1).
# Pulls whatever sources have real credentials in config.env (others stay
# "pending_credentials"), re-renders dashboard/index.html, and commits the
# result to the GitHub repo so the history keeps building even though
# republishing the live Artifact still needs a manual step in a Claude Code
# session (local Task Scheduler can't call the Artifact tool).

$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Administrator\Desktop\test"
$log = "data\sync_log.txt"

function Log($msg) {
    "$(Get-Date -Format o)  $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

try {
    $py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
    $out = & $py scripts\sync_dashboard.py 2>&1 | Out-String
    Log $out

    git add data\daily_metrics.jsonl docs\index.html
    $status = git status --porcelain
    if ($status) {
        git -c user.email="bot@local" -c user.name="dashboard-bot" commit -m "Daily sync $(Get-Date -Format yyyy-MM-dd)" | Out-Null

        # Push token lives only in scripts/config.env (gitignored) -- add a line
        # there yourself: GITHUB_PUSH_TOKEN=ghp_xxx (a fine-grained token scoped
        # to just this repo, Contents: Read and write). Never typed/stored by
        # Claude. If it's missing, the commit stays local until you add it and
        # re-run (or push manually).
        $tokenLine = Get-Content scripts\config.env -ErrorAction SilentlyContinue | Select-String '^GITHUB_PUSH_TOKEN=(.+)$'
        if ($tokenLine) {
            $token = $tokenLine.Matches[0].Groups[1].Value.Trim()
            git push "https://$token@github.com/qwqess121/pureamor-ops-dashboard.git" main | Out-Null
            Log "committed and pushed"
        } else {
            Log "committed locally but GITHUB_PUSH_TOKEN not set in scripts/config.env -- push skipped"
        }
    } else {
        Log "no changes to commit"
    }
} catch {
    Log "ERROR: $_"
}
