# GreenShift Kubernetes Deployment & Operations

## 1. Overview

GreenShift is deployed onto Kubernetes as a set of decoupled microservices and orchestrates compute jobs natively within the cluster.

---

## 2. Resource Hierarchy

```
Namespace: greenshift
├── RBAC
│   ├── ServiceAccount: greenshift-dispatcher
│   ├── Role: greenshift-dispatcher-role (batch/jobs, pods, pods/log)
│   └── RoleBinding: greenshift-dispatcher-rolebinding
├── Config & Secrets
│   ├── Secret: greenshift-api-secrets (ELECTRICITY_MAPS_API_KEY)
│   ├── ConfigMap: greenshift-config (General environment config)
│   └── ConfigMap: greenshift-tariff-data (Mounted Indian ToU CSV)
├── Storage & State
│   └── Deployment: postgres (PostgreSQL 15 Alpine)
│   └── Service: postgres (ClusterIP, port 5432)
├── Core Agents
│   ├── Deployment: greenshift-api (Port 8000)
│   ├── Deployment: greenshift-ingest (Worker loop)
│   ├── Deployment: greenshift-scheduler (Worker loop)
│   ├── Deployment: greenshift-dispatcher (Worker loop with ServiceAccount)
│   └── Deployment: greenshift-trust (Worker loop)
└── Presentation
    ├── Deployment: greenshift-dashboard (Port 8501)
    └── Service: greenshift-dashboard (NodePort: 30501 / ClusterIP)
```

---

## 3. Workload Job Template

When GreenShift dispatches a scheduled job, it generates a Kubernetes `batch/v1` Job:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: gs-job-demo-001
  namespace: greenshift
  labels:
    app: greenshift
    greenshift-job-id: JOB-DEMO-001
    greenshift-team-id: analytics-team
spec:
  backoffLimit: 2
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        app: greenshift
        greenshift-job-id: JOB-DEMO-001
    spec:
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
      containers:
        - name: workload
          image: greenshift/sample-workload:latest
          imagePullPolicy: IfNotPresent
          env:
            - name: JOB_ID
              value: "JOB-DEMO-001"
            - name: TEAM_ID
              value: "analytics-team"
            - name: DURATION_SECONDS
              value: "600"
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "1000m"
              memory: "1024Mi"
```

---

## 4. Operational Commands

### Deployment
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/tariff-configmap.yaml
kubectl apply -f k8s/services.yaml
kubectl apply -f k8s/deployments.yaml
```

### Inspect Pods & Services
```bash
kubectl get pods -n greenshift -o wide
kubectl get services -n greenshift
kubectl get jobs -n greenshift
```

### Accessing Dashboard Locally
```bash
# Port forward to localhost
kubectl port-forward -n greenshift svc/greenshift-dashboard 8501:8501
```
