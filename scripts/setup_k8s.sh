#!/usr/bin/env bash
# =============================================================================
# GreenShift Kubernetes Cluster Setup Script
# Works with Docker Desktop, Minikube, or Kind.
# Applies all manifests in dependency order and waits for healthy pods.
# =============================================================================

set -euo pipefail

echo "============================================================"
echo "GreenShift Kubernetes Setup"
echo "============================================================"

# 1. Detect cluster context
CURRENT_CONTEXT=$(kubectl config current-context 2>/dev/null || echo "none")
echo "Current Kubernetes Context: ${CURRENT_CONTEXT}"

if [ "${CURRENT_CONTEXT}" = "none" ]; then
    echo "ERROR: No active Kubernetes context found. Please start Docker Desktop K8s or Minikube."
    exit 1
fi

# 2. Check Minikube docker-env if on minikube
if [ "${CURRENT_CONTEXT}" = "minikube" ]; then
    echo "Detected Minikube context — pointing shell to Minikube Docker daemon..."
    eval $(minikube docker-env)
fi

# 3. Create namespace
echo "[1/7] Applying namespace..."
kubectl apply -f k8s/namespace.yaml

# 4. Apply secrets
echo "[2/7] Applying secrets..."
kubectl apply -f k8s/secrets.yaml

# 5. Apply configmaps
echo "[3/7] Applying configmap..."
kubectl apply -f k8s/configmap.yaml

if [ -f k8s/tariff-configmap.yaml ]; then
    echo "[4/7] Applying tariff configmap..."
    kubectl apply -f k8s/tariff-configmap.yaml
fi

# 6. Apply RBAC
echo "[5/7] Applying RBAC..."
kubectl apply -f k8s/rbac.yaml

# 7. Apply Services
echo "[6/7] Applying services..."
kubectl apply -f k8s/services.yaml

# 8. Apply Deployments
echo "[7/7] Applying deployments..."
kubectl apply -f k8s/deployments.yaml

echo "Manifests applied successfully."
echo "Waiting for deployments to roll out in namespace 'greenshift'..."

# Wait for postgres first so services can connect
kubectl rollout status deployment/postgres -n greenshift --timeout=120s || true

# Wait for all greenshift pods to become ready
echo "Waiting for all GreenShift pods to be ready..."
kubectl wait --namespace greenshift --for=condition=ready pod -l app=greenshift --timeout=120s || true

echo "============================================================"
echo "GreenShift Cluster Status"
echo "============================================================"
kubectl get pods -n greenshift -o wide
kubectl get svc -n greenshift
echo "============================================================"
echo "GreenShift Kubernetes setup complete."
