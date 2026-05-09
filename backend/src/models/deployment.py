from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Feature 004 / 005 / 006 — personal-repo mock deployment models               #
# Kept unchanged for backward compatibility with existing contract tests.      #
# --------------------------------------------------------------------------- #

class ResourceType(str, Enum):
    CPU = "CPU"
    GPU = "GPU"


class DeploymentStatus(str, Enum):
    pending = "pending"
    mock_success = "mock_success"


class MockDeployment(BaseModel):
    model_repository: str
    resource_type: ResourceType
    deployment_status: DeploymentStatus = DeploymentStatus.pending


class MockDeploymentRequest(BaseModel):
    model_repository: str
    resource_type: ResourceType


class MockDeploymentResponse(BaseModel):
    status: str
    message: str


# --------------------------------------------------------------------------- #
# Feature 007 — real GKE deployment models                                     #
# --------------------------------------------------------------------------- #

class GkeDeploymentStatus(str, Enum):
    queued = "queued"
    deploying = "deploying"
    running = "running"
    failed = "failed"
    deleting = "deleting"
    deleted = "deleted"
    lost = "lost"


class DeployRequest(BaseModel):
    hf_model_id: str = Field(..., description="HuggingFace model repository ID, e.g. Qwen/Qwen3-1.7B")
    force: bool = Field(default=False, description="Bypass the duplicate-model confirmation (FR-016).")


class Deployment(BaseModel):
    id: str
    hf_model_id: str
    hf_model_display_name: str
    status: GkeDeploymentStatus
    status_message: str | None = None
    endpoint_url: str | None = None
    created_at: datetime
    updated_at: datetime


class DeploymentDetail(Deployment):
    gcp_project_id: str
    gke_cluster_name: str
    gke_region: str
    gcp_console_url: str
