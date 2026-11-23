param(
    [string]$PrometheusUrl = "http://127.0.0.1:9090",
    [string]$GrafanaUrl = "http://127.0.0.1:3000",
    [string]$GrafanaUser = $env:GRAFANA_USER,
    [string]$GrafanaPassword = $env:GRAFANA_PASSWORD
)

$ErrorActionPreference = "Stop"
$failed = $false

function Fail([string]$message) {
    Write-Host "FAIL: $message"
    $script:failed = $true
}

try {
    $targets = Invoke-RestMethod "$PrometheusUrl/api/v1/targets" -TimeoutSec 10
    $flowsmith = @($targets.data.activeTargets | Where-Object { $_.labels.job -eq "flowsmith" })
    if ($flowsmith.Count -eq 0) {
        Fail "Prometheus has no flowsmith scrape target"
    } elseif (@($flowsmith | Where-Object { $_.health -ne "up" }).Count -gt 0) {
        Fail "Prometheus flowsmith target is not up: $($flowsmith | ConvertTo-Json -Compress)"
    } else {
        Write-Host "PASS: Prometheus scrapes flowsmith ($($flowsmith[0].scrapeUrl))"
    }
} catch {
    Fail "Prometheus targets query failed: $($_.Exception.Message)"
}

try {
    $rules = Invoke-RestMethod "$PrometheusUrl/api/v1/rules" -TimeoutSec 10
    $names = @($rules.data.groups | ForEach-Object { $_.rules } | Where-Object { $_.type -eq "alerting" } | ForEach-Object { $_.name })
    foreach ($required in @("FlowsmithMetricsDown", "FlowsmithExecutionFailureRateHigh", "FlowsmithQueueBacklogHigh", "FlowsmithQueueWorkersStalled", "FlowsmithWebhookDeliveryFailures")) {
        if ($names -notcontains $required) {
            Fail "Prometheus alert rule missing: $required"
        }
    }
    if (-not $failed) {
        Write-Host "PASS: 5 Flowsmith alert rules loaded"
    }
} catch {
    Fail "Prometheus rules query failed: $($_.Exception.Message)"
}

if (-not $GrafanaUser -or -not $GrafanaPassword) {
    Fail "GRAFANA_USER / GRAFANA_PASSWORD are not set"
} else {
    $pair = "${GrafanaUser}:${GrafanaPassword}"
    $basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
    try {
        $dashboard = Invoke-RestMethod "$GrafanaUrl/api/dashboards/uid/flowsmith" -Headers @{ Authorization = "Basic $basic" } -TimeoutSec 10
        $panels = @($dashboard.dashboard.panels)
        if ($dashboard.dashboard.title -ne "Flowsmith") {
            Fail "Unexpected Grafana dashboard title: $($dashboard.dashboard.title)"
        } elseif ($panels.Count -lt 7) {
            Fail "Grafana dashboard has $($panels.Count) panels, expected 7"
        } else {
            Write-Host "PASS: Grafana dashboard 'Flowsmith' loaded with $($panels.Count) panels"
        }
    } catch {
        Fail "Grafana dashboard query failed: $($_.Exception.Message)"
    }
}

if ($failed) {
    exit 1
}
Write-Host "Monitoring validation passed."
exit 0
