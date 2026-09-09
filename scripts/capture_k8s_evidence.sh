#!/usr/bin/env bash
# =============================================================================
# GreenShift Kubernetes Validation Evidence Collector
# Captures cluster state, pod logs, E2E test runs, and audit verification.
# =============================================================================

set -euo pipefail

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
EVIDENCE_DIR="evidence/k8s-validation-${TIMESTAMP}"
mkdir -p "${EVIDENCE_DIR}"

echo "============================================================"
echo "Capturing GreenShift Live Kubernetes Validation Evidence"
echo "Target Directory: ${EVIDENCE_DIR}"
echo "============================================================"

# 1. Cluster Information
echo "[1/6] Capturing cluster information..."
{
    echo "=== KUBECTL CLUSTER-INFO ==="
    kubectl cluster-info
    echo -e "\n=== KUBERNETES NODES ==="
    kubectl get nodes -o wide
    echo -e "\n=== NAMESPACES ==="
    kubectl get namespaces
} > "${EVIDENCE_DIR}/01_cluster_info.txt" 2>&1

# 2. GreenShift Namespace Resources
echo "[2/6] Capturing GreenShift namespace resources..."
{
    echo "=== PODS IN GREENSHIFT NAMESPACE ==="
    kubectl get pods -n greenshift -o wide
    echo -e "\n=== SERVICES IN GREENSHIFT NAMESPACE ==="
    kubectl get svc -n greenshift -o wide
    echo -e "\n=== DEPLOYMENTS IN GREENSHIFT NAMESPACE ==="
    kubectl get deployments -n greenshift -o wide
    echo -e "\n=== CONFIGMAPS ==="
    kubectl get configmap -n greenshift
    echo -e "\n=== RBAC (SA, ROLES, BINDINGS) ==="
    kubectl get serviceaccount,role,rolebinding -n greenshift
} > "${EVIDENCE_DIR}/02_k8s_resources.txt" 2>&1

# 3. Run Live E2E Pipeline and Capture Output
echo "[3/6] Running Live E2E Validation Script..."
python scripts/run_live_e2e_test.py > "${EVIDENCE_DIR}/03_e2e_test_output.txt" 2>&1 || true

# 4. Capture Pod Logs from all GreenShift pods
echo "[4/6] Capturing GreenShift component logs..."
for pod in $(kubectl get pods -n greenshift -o jsonpath='{.items[*].metadata.name}'); do
    echo "Capturing logs for ${pod}..."
    kubectl logs "${pod}" -n greenshift > "${EVIDENCE_DIR}/pod_log_${pod}.txt" 2>&1 || true
done

# 5. Run Pytest K8s Integration Suite and Capture Output
echo "[5/6] Running Pytest K8s Integration Suite..."
pytest tests/test_k8s_integration.py -v > "${EVIDENCE_DIR}/05_pytest_k8s_integration.txt" 2>&1 || true

# 6. Summary Manifest
echo "[6/6] Generating evidence manifest..."
{
    echo "GreenShift Live Kubernetes Validation Evidence Summary"
    echo "Timestamp: ${TIMESTAMP}"
    echo "Directory: ${EVIDENCE_DIR}"
    echo "Files Captured:"
    ls -la "${EVIDENCE_DIR}"
} > "${EVIDENCE_DIR}/00_manifest.txt"

echo "============================================================"
echo "Evidence capture complete. Artifacts saved in ${EVIDENCE_DIR}"
echo "============================================================"
