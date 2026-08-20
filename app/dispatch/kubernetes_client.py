"""
Agent 3 — DISPATCH
Kubernetes client initialisation.

Supports:
  - In-cluster config (when running inside Kubernetes)
  - Local kubeconfig (development)
"""

import logging
from typing import Optional

from kubernetes import client, config
from kubernetes.client import ApiClient, BatchV1Api, CoreV1Api
from kubernetes.client.rest import ApiException

from app.shared.config import settings

logger = logging.getLogger(__name__)

_api_client: Optional[ApiClient] = None


def _load_kube_config() -> None:
    """Load Kubernetes configuration once."""
    global _api_client
    if _api_client is not None:
        return

    if settings.k8s_in_cluster:
        logger.info("Loading in-cluster Kubernetes config")
        config.load_incluster_config()
    else:
        logger.info("Loading local kubeconfig")
        config.load_kube_config()

    _api_client = ApiClient()


def get_batch_v1() -> BatchV1Api:
    """Return a configured BatchV1Api client."""
    _load_kube_config()
    return BatchV1Api(_api_client)


def get_core_v1() -> CoreV1Api:
    """Return a configured CoreV1Api client."""
    _load_kube_config()
    return CoreV1Api(_api_client)


def check_kubernetes_available() -> bool:
    """Return True if Kubernetes API is reachable."""
    try:
        core = get_core_v1()
        core.list_namespace(limit=1, _request_timeout=5)
        return True
    except Exception as exc:
        logger.warning("Kubernetes API unavailable: %s", exc)
        return False
