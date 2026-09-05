# GreenShift — Complete Kubernetes Integration Guide

This guide documents the dual-mode architecture and integration of GreenShift with Kubernetes. GreenShift seamlessly supports:
1. **Local Development Mode (`K8S_IN_CLUSTER=false`)**: Docker Compose services run on the host while the Dispatcher container connects to your local Kubernetes cluster.
2. **Kubernetes-Native Mode (`K8S_IN_CLUSTER=true`)**: All GreenShift microservices (API, Ingest, Scheduler, Dispatcher, Trust) run inside Kubernetes Pods using in-cluster ServiceAccount credentials.

---

## 1. Architecture Overview

```mermaid
flowchart TD
    subgraph Host["Host Machine (Windows / PowerShell)"]
        K8S["Local Kubernetes Cluster (desktop-control-plane)"]
        KubeConfig["~/.kube/config"]
    end

    subgraph DockerCompose["Docker Compose Environment"]
        API["greenshift-api (:8000)"]
        Ingest["greenshift-ingest"]
        Scheduler["greenshift-scheduler"]
        Trust["greenshift-trust"]
        Dashboard["greenshift-dashboard (:8501)"]
        
        subgraph DispatcherService["greenshift-dispatcher Container"]
            D_Loop["app.dispatch.service (Dispatch Loop)"]
            K8S_Client["app.dispatch.kubernetes_client"]
            JobBuilder["app.dispatch.job_builder"]
            StatusTracker["app.dispatch.status_tracker"]
        end
    end

    API --> Ingest
    Ingest --> Scheduler
    Scheduler --> DispatcherService
    DispatcherService --> Trust
    
    KubeConfig -.->|Mounted read-only| DispatcherService
    K8S_Client -->|"K8S_IN_CLUSTER=false (via desktop-control-plane / host.docker.internal)"| K8S
    K8S -->|"Creates batch/v1 Job"| WorkloadPod["Workload Pod (greenshift/sample-workload:latest)"]
    StatusTracker -.->|"Polls Job & Pod Lifecycle"| K8S
    StatusTracker -->|"Records Transitions to Hash-Chain"| Trust
```

---

## 2. Execution Modes Comparison

| Configuration Setting | Mode A: Local Development | Mode B: In-Cluster Kubernetes |
| :--- | :--- | :--- |
| **`K8S_IN_CLUSTER`** | `false` | `true` |
| **Credential Source** | Mounted `~/.kube/config` (read-only) | ServiceAccount token (`/var/run/secrets/kubernetes.io/serviceaccount`) |
| **ServiceAccount** | N/A (uses local user context) | `greenshift-dispatcher` |
| **API Endpoint** | `https://desktop-control-plane:63799` or `https://host.docker.internal:63799` | `https://kubernetes.default.svc` |
| **Environment** | Docker Compose | Kubernetes Deployment (`k8s/deployments.yaml`) |
| **Mount Requirements** | `${USERPROFILE:-~}/.kube:/home/greenshift/.kube:ro` | None required (automatic by K8s) |

---

## 3. Local Development Mode (Docker Compose -> Kubernetes)

### Prerequisites
- Docker Desktop with Kubernetes or Kind running
- Namespace created: `greenshift`
- RBAC applied: `k8s/rbac.yaml`

### Step 1: Build the Sample Workload Image & Import to Cluster
```powershell
# Build workload image locally
docker build -t greenshift/sample-workload:latest sample-workload

# Import image into local cluster node containerd runtime
docker save -o workload.tar greenshift/sample-workload:latest
docker cp workload.tar desktop-control-plane:/workload.tar
docker exec desktop-control-plane ctr --namespace=k8s.io images import /workload.tar
docker exec desktop-control-plane rm /workload.tar
Remove-Item -Force workload.tar
```

### Step 2: Configure Environment Variables
In `.env`:
```env
K8S_NAMESPACE=greenshift
K8S_IN_CLUSTER=false
```

In `docker-compose.yml`:
```yaml
  dispatcher:
    build:
      context: .
      dockerfile: Dockerfile.dispatcher
    image: greenshift/dispatcher:latest
    container_name: greenshift-dispatcher
    environment:
      - DATABASE_URL=sqlite:////data/greenshift.db
      - LOG_LEVEL=INFO
      - K8S_IN_CLUSTER=false
      - K8S_NAMESPACE=greenshift
      - KUBECONFIG=/home/greenshift/.kube/config
    env_file:
      - .env
    volumes:
      - greenshift-data:/data
      - ${USERPROFILE:-~}/.kube:/home/greenshift/.kube:ro
      - ${USERPROFILE:-~}/.kube:/root/.kube:ro
    extra_hosts:
      - "host.docker.internal:host-gateway"
      - "desktop-control-plane:host-gateway"
```

### Step 3: Start Services
```powershell
docker compose up -d
docker compose ps
```

### Step 4: Verify Connectivity from Inside Dispatcher Container
```powershell
docker exec greenshift-dispatcher python -c "from app.dispatch.kubernetes_client import check_kubernetes_available; print('K8S available in dispatcher:', check_kubernetes_available())"
```

---

## 4. Kubernetes-Native Deployment Mode

When deploying GreenShift fully on Kubernetes:

### Step 1: Apply RBAC & Namespace
```powershell
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/rbac.yaml
```

The ServiceAccount `greenshift-dispatcher` is bound to `greenshift-dispatcher-role` with least-privilege permissions:
- **Jobs**: `create`, `get`, `list`, `watch`, `delete`
- **Pods**: `get`, `list`, `watch`
- **Pod Logs**: `get`

### Step 2: Apply ConfigMap & Secrets
```powershell
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/tariff-configmap.yaml
kubectl apply -f k8s/secrets.example.yaml
```

In `k8s/configmap.yaml`:
```yaml
K8S_IN_CLUSTER: "true"
K8S_NAMESPACE: "greenshift"
```

### Step 3: Apply Deployments & Services
```powershell
kubectl apply -f k8s/deployments.yaml
kubectl apply -f k8s/services.yaml
```

The dispatcher deployment in `k8s/deployments.yaml` automatically utilizes the ServiceAccount:
```yaml
spec:
  serviceAccountName: greenshift-dispatcher
```

---

## 5. Verification Commands

### Check Kubernetes Resources
```powershell
# List all active and completed Jobs
kubectl get jobs -n greenshift

# List Pods and execution statuses
kubectl get pods -n greenshift

# View logs from a specific workload pod
kubectl logs <pod-name> -n greenshift

# Inspect GreenShift labels & annotations
kubectl describe job <job-name> -n greenshift
```

### Run Automated E2E Verification
```powershell
$env:PYTHONPATH="."
python scripts/verify_k8s_e2e.py
```

### Run Unit Tests
```powershell
pytest tests/test_dispatch_k8s.py -v
```

---

## 6. Lifecycle & State Machine

1. **`SUBMITTED`**: Job ingested with deadline, power, runtime, and container image (`greenshift/sample-workload:latest`).
2. **`SCHEDULED`**: DECIDE agent calculates optimal carbon intensity slot and assigns `selected_start`.
3. **`QUEUED`**: DISPATCH agent generates `batch/v1` Job and submits it to Kubernetes API.
4. **`RUNNING`**: Status tracker detects active Pod in `Running` state and logs pod start time.
5. **`COMPLETED`**: Workload finishes with exit code 0; Status tracker marks completion and finalizes Trust Audit hash-chain.
