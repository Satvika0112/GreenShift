# =============================================================================
# GreenShift Kubernetes Cluster Setup Script (PowerShell)
# Works with Docker Desktop, Minikube, or Kind.
# Applies all manifests in dependency order and waits for healthy pods.
# =============================================================================

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "GreenShift Kubernetes Setup (PowerShell)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Detect cluster context
$context = (kubectl config current-context) 2>$null
Write-Host "Current Kubernetes Context: $context" -ForegroundColor Green

if (-not $context) {
    Write-Error "ERROR: No active Kubernetes context found. Please start Docker Desktop K8s or Minikube."
    exit 1
}

# 2. Apply Namespace
Write-Host "[1/7] Applying namespace..." -ForegroundColor Yellow
kubectl apply -f k8s/namespace.yaml

# 3. Apply Secrets
Write-Host "[2/7] Applying secrets..." -ForegroundColor Yellow
kubectl apply -f k8s/secrets.yaml

# 4. Apply ConfigMaps
Write-Host "[3/7] Applying configmap..." -ForegroundColor Yellow
kubectl apply -f k8s/configmap.yaml

if (Test-Path "k8s/tariff-configmap.yaml") {
    Write-Host "[4/7] Applying tariff configmap..." -ForegroundColor Yellow
    kubectl apply -f k8s/tariff-configmap.yaml
}

# 5. Apply RBAC
Write-Host "[5/7] Applying RBAC..." -ForegroundColor Yellow
kubectl apply -f k8s/rbac.yaml

# 6. Apply Services
Write-Host "[6/7] Applying services..." -ForegroundColor Yellow
kubectl apply -f k8s/services.yaml

# 7. Apply Deployments
Write-Host "[7/7] Applying deployments..." -ForegroundColor Yellow
kubectl apply -f k8s/deployments.yaml

Write-Host "Manifests applied successfully." -ForegroundColor Green
Write-Host "Waiting for deployments to roll out in namespace 'greenshift'..." -ForegroundColor Yellow

# Wait for postgres first
kubectl rollout status deployment/postgres -n greenshift --timeout=120s

# Wait for all greenshift pods to become ready
Write-Host "Waiting for all GreenShift pods to be ready..." -ForegroundColor Yellow
kubectl wait --namespace greenshift --for=condition=ready pod -l app=greenshift --timeout=120s

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "GreenShift Cluster Status" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
kubectl get pods -n greenshift -o wide
kubectl get svc -n greenshift
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "GreenShift Kubernetes setup complete." -ForegroundColor Green
