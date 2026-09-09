# =============================================================================
# GreenShift Kubernetes Validation Evidence Collector (PowerShell)
# Captures cluster state, pod logs, E2E test runs, and audit verification.
# =============================================================================

$timestamp = (Get-Date -Format "yyyyMMdd_HHmmss")
$evidenceDir = "evidence\k8s-validation-$timestamp"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Capturing GreenShift Live Kubernetes Validation Evidence" -ForegroundColor Cyan
Write-Host "Target Directory: $evidenceDir" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Cluster Information
Write-Host "[1/6] Capturing cluster information..." -ForegroundColor Yellow
& {
    Write-Host "=== KUBECTL CLUSTER-INFO ==="
    kubectl cluster-info
    Write-Host "`n=== KUBERNETES NODES ==="
    kubectl get nodes -o wide
    Write-Host "`n=== NAMESPACES ==="
    kubectl get namespaces
} *>&1 | Out-File -FilePath "$evidenceDir\01_cluster_info.txt" -Encoding utf8

# 2. Namespace Resources
Write-Host "[2/6] Capturing GreenShift namespace resources..." -ForegroundColor Yellow
& {
    Write-Host "=== PODS IN GREENSHIFT NAMESPACE ==="
    kubectl get pods -n greenshift -o wide
    Write-Host "`n=== SERVICES IN GREENSHIFT NAMESPACE ==="
    kubectl get svc -n greenshift -o wide
    Write-Host "`n=== DEPLOYMENTS IN GREENSHIFT NAMESPACE ==="
    kubectl get deployments -n greenshift -o wide
    Write-Host "`n=== CONFIGMAPS ==="
    kubectl get configmap -n greenshift
    Write-Host "`n=== RBAC (SA, ROLES, BINDINGS) ==="
    kubectl get serviceaccount,role,rolebinding -n greenshift
} *>&1 | Out-File -FilePath "$evidenceDir\02_k8s_resources.txt" -Encoding utf8

# 3. Live E2E Pipeline
Write-Host "[3/6] Running Live E2E Validation Script..." -ForegroundColor Yellow
python scripts\run_live_e2e_test.py *>&1 | Tee-Object -FilePath "$evidenceDir\03_e2e_test_output.txt"

# 4. Pod Logs
Write-Host "[4/6] Capturing GreenShift component logs..." -ForegroundColor Yellow
$pods = (kubectl get pods -n greenshift -o jsonpath="{.items[*].metadata.name}").Split(" ")
foreach ($pod in $pods) {
    if ($pod) {
        Write-Host "Capturing logs for $pod..."
        kubectl logs $pod -n greenshift *>&1 | Out-File -FilePath "$evidenceDir\pod_log_$pod.txt" -Encoding utf8
    }
}

# 5. Pytest K8s Integration Suite
Write-Host "[5/6] Running Pytest K8s Integration Suite..." -ForegroundColor Yellow
pytest tests\test_k8s_integration.py -v *>&1 | Tee-Object -FilePath "$evidenceDir\05_pytest_k8s_integration.txt"

# 6. Summary Manifest
Write-Host "[6/6] Generating evidence manifest..." -ForegroundColor Yellow
& {
    Write-Host "GreenShift Live Kubernetes Validation Evidence Summary"
    Write-Host "Timestamp: $timestamp"
    Write-Host "Directory: $evidenceDir"
    Write-Host "`nFiles Captured:"
    Get-ChildItem -Path $evidenceDir | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
} *>&1 | Out-File -FilePath "$evidenceDir\00_manifest.txt" -Encoding utf8

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Evidence capture complete. Artifacts saved in $evidenceDir" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
